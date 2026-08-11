#!/usr/bin/env python3
"""Safely ad-hoc sign macOS frontend and packaged-runtime native artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Mapping


def _ensure_project_root_on_sys_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    return project_root


_PROJECT_ROOT = _ensure_project_root_on_sys_path()

from src.scripts.sign_macos_backend_runtime import (  # noqa: E402
    _PathIdentity,
    _assert_plain_directory,
    _assert_plain_file,
    _assert_resolved_containment,
    _cleanup_private_staging_root,
    _directory_open_flags,
    _identity_from_stat,
    _identity_is_link,
    _load_codesign_state,
    _open_validated_directory,
    _path_identity,
    _same_directory_identity,
    _sha256_file,
    _stamp_entry_identity,
    _unlink_codesign_stamp,
    write_macos_backend_codesign_state,
)
from src.utils.subprocess_safety import (  # noqa: E402
    BoundedTextEmitter,
    DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
    bounded_process_failure_detail,
    run_bounded_subprocess,
)


STAGING_PREFIX = ".vantage-codesign-staging-"
FRONTEND_STAMP_NAME = ".macos-native-codesign.sha256"
STATE_SCHEMA_VERSION = 1
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


@dataclass(frozen=True)
class MacOSArtifactSigningOutcome:
    reused: bool
    artifact_count: int
    skipped: bool = False


@dataclass(frozen=True)
class _Artifact:
    path: Path
    relative_path: str
    identity: _PathIdentity
    parent_identity: _PathIdentity
    sha256: str


@dataclass(frozen=True)
class _ArtifactLink:
    relative_path: str
    raw_target: str
    resolved_target: str
    identity: _PathIdentity
    target_identity: _PathIdentity


@dataclass(frozen=True)
class _ArtifactSnapshot:
    root_identity: _PathIdentity
    anchor_identity: _PathIdentity | None
    anchor_sha256: str | None
    artifacts: tuple[_Artifact, ...]
    links: tuple[_ArtifactLink, ...]


@dataclass(frozen=True)
class _StagedArtifact:
    source: _Artifact
    path: Path
    identity: _PathIdentity
    parent_identity: _PathIdentity
    sha256: str


def _absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(path))


def _expected_profile_paths(
    project_root: Path,
    profile: str,
) -> tuple[Path, Path | None, Path | None]:
    if profile == "frontend":
        webapp = project_root / "src" / "webapp"
        root = webapp / "node_modules"
        return root, webapp / "package-lock.json", root / FRONTEND_STAMP_NAME
    if profile == "backend-bundle":
        root = project_root / "build" / "backend-runtime" / "stage" / "VantageBackend"
        return root, None, None
    raise ValueError(f"unsupported macOS artifact signing profile: {profile}")


def _validate_profile_paths(
    project_root: Path,
    root: Path,
    profile: str,
    stamp_path: Path | None,
) -> tuple[Path | None, Path | None]:
    expected_root, anchor_path, expected_stamp = _expected_profile_paths(
        project_root,
        profile,
    )
    if os.path.normcase(str(root)) != os.path.normcase(str(expected_root)):
        raise ValueError("macOS artifact signer received an unexpected expected root")
    if profile == "frontend":
        if stamp_path is None or os.path.normcase(str(stamp_path)) != os.path.normcase(
            str(expected_stamp)
        ):
            raise ValueError("macOS frontend signer received an unexpected stamp path")
    elif stamp_path is not None:
        raise ValueError("macOS backend bundle signer does not accept a stamp path")

    project_identity = _assert_plain_directory(project_root, role="project root")
    root_identity = _assert_plain_directory(root, role="artifact root")
    _assert_resolved_containment(root, project_root, role="artifact root")
    if not _same_directory_identity(
        _assert_plain_directory(project_root, role="project root"),
        project_identity,
    ):
        raise RuntimeError("macOS artifact project root identity changed")
    if not _same_directory_identity(
        _assert_plain_directory(root, role="artifact root"),
        root_identity,
    ):
        raise RuntimeError("macOS artifact root identity changed")
    return anchor_path, expected_stamp


def _matches_frontend(relative_path: str) -> bool:
    if relative_path == "electron" or relative_path.startswith("electron/"):
        return False
    path = Path(relative_path)
    if path.suffix in {".node", ".dylib"}:
        return True
    return any(
        fnmatch.fnmatchcase(relative_path, pattern)
        for pattern in (
            "@esbuild/*/bin/esbuild",
            "app-builder-bin/mac/app-builder*",
            "7zip-bin/mac/*/7za",
        )
    )


def _matches_profile(relative_path: str, profile: str) -> bool:
    if profile == "frontend":
        return _matches_frontend(relative_path)
    path = Path(relative_path)
    return path.suffix in {".so", ".dylib"} or path.name in {
        "VantageBackend",
        "Python",
    }


def _is_macho_file(path: Path) -> bool:
    identity = _path_identity(path)
    if _identity_is_link(identity) or not stat.S_ISREG(identity.file_type):
        return False
    flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    try:
        if _identity_from_stat(os.fstat(descriptor)) != identity:
            raise RuntimeError("macOS frontend artifact identity changed before probing")
        magic = os.read(descriptor, 4)
        if _identity_from_stat(os.fstat(descriptor)) != identity:
            raise RuntimeError("macOS frontend artifact identity changed while probing")
    finally:
        os.close(descriptor)
    if _path_identity(path) != identity:
        raise RuntimeError("macOS frontend artifact identity changed after probing")
    return magic in MACHO_MAGICS


def _assert_parent_chain(root: Path, parent: Path) -> None:
    relative = parent.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        _assert_plain_directory(current, role="artifact parent")
    _assert_resolved_containment(parent, root, role="artifact parent")


def _inspect_backend_link(root: Path, path: Path) -> _ArtifactLink:
    identity = _path_identity(path)
    try:
        raw_target = os.readlink(path)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError(
            "macOS backend bundle contains an external or escaped link"
        ) from exc
    target_identity = _path_identity(resolved)
    if _identity_is_link(target_identity):
        raise ValueError("macOS backend bundle link did not resolve to a plain target")
    return _ArtifactLink(
        relative_path=path.relative_to(root).as_posix(),
        raw_target=str(raw_target),
        resolved_target=resolved.relative_to(root.resolve(strict=True)).as_posix(),
        identity=identity,
        target_identity=target_identity,
    )


def _candidate_paths(
    root: Path,
    profile: str,
    *,
    ignored_root: Path | None,
) -> tuple[list[Path], tuple[_ArtifactLink, ...]]:
    candidates: list[Path] = []
    links: list[_ArtifactLink] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        if ignored_root is not None and directory_path == ignored_root:
            directory_names[:] = []
            continue
        kept_directories: list[str] = []
        for name in directory_names:
            child = directory_path / name
            if ignored_root is not None and child == ignored_root:
                continue
            identity = _path_identity(child)
            if _identity_is_link(identity):
                if profile == "backend-bundle":
                    links.append(_inspect_backend_link(root, child))
                else:
                    raise ValueError(
                        "macOS frontend artifact directory must not be a link"
                    )
                continue
            if stat.S_ISDIR(identity.file_type):
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in file_names:
            path = directory_path / name
            relative_path = path.relative_to(root).as_posix()
            identity = _path_identity(path)
            if _identity_is_link(identity):
                if profile == "backend-bundle":
                    link = _inspect_backend_link(root, path)
                    links.append(link)
                    if _matches_profile(relative_path, profile):
                        resolved = path.resolve(strict=True)
                        if not stat.S_ISREG(_path_identity(resolved).file_type):
                            raise ValueError(
                                "macOS backend bundle native link target is not a file"
                            )
                        candidates.append(resolved)
                elif _matches_profile(relative_path, profile):
                    raise ValueError(
                        "macOS frontend native artifact must not be a link"
                    )
                continue
            if not _matches_profile(relative_path, profile):
                continue
            if profile == "frontend" and not _is_macho_file(path):
                raise ValueError(
                    "macOS frontend native artifact is not a valid Mach-O file: "
                    f"{relative_path}"
                )
            candidates.append(path)

    unique_candidates = {
        os.path.normcase(str(path)): path
        for path in candidates
    }
    return (
        sorted(
            unique_candidates.values(),
            key=lambda path: path.relative_to(root).as_posix(),
        ),
        tuple(sorted(links, key=lambda link: link.relative_path)),
    )


def _build_snapshot(
    root: Path,
    profile: str,
    anchor_path: Path | None,
    *,
    ignored_root: Path | None = None,
) -> _ArtifactSnapshot:
    root_identity = _assert_plain_directory(root, role="artifact root")
    artifacts: list[_Artifact] = []
    candidate_paths, links = _candidate_paths(
        root,
        profile,
        ignored_root=ignored_root,
    )
    for path in candidate_paths:
        _assert_parent_chain(root, path.parent)
        identity = _assert_plain_file(path, role="native artifact")
        _assert_resolved_containment(path, root, role="native artifact")
        parent_identity = _assert_plain_directory(
            path.parent,
            role="artifact parent",
        )
        artifacts.append(
            _Artifact(
                path=path,
                relative_path=path.relative_to(root).as_posix(),
                identity=identity,
                parent_identity=parent_identity,
                sha256=_sha256_file(
                    path,
                    expected_identity=identity,
                    role="native artifact",
                ),
            )
        )

    anchor_identity: _PathIdentity | None = None
    anchor_sha256: str | None = None
    if anchor_path is not None:
        anchor_identity = _assert_plain_file(anchor_path, role="profile state")
        anchor_sha256 = _sha256_file(
            anchor_path,
            expected_identity=anchor_identity,
            role="profile state",
        )
    if not _same_directory_identity(
        _assert_plain_directory(root, role="artifact root"),
        root_identity,
    ):
        raise RuntimeError("macOS artifact root identity changed during scan")
    return _ArtifactSnapshot(
        root_identity=root_identity,
        anchor_identity=anchor_identity,
        anchor_sha256=anchor_sha256,
        artifacts=tuple(artifacts),
        links=links,
    )


def _snapshot_state(profile: str, snapshot: _ArtifactSnapshot) -> dict[str, object]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "profile": profile,
        "profile_state_sha256": snapshot.anchor_sha256,
        "artifacts": [
            {
                "path": artifact.relative_path,
                "sha256": artifact.sha256,
            }
            for artifact in snapshot.artifacts
        ],
        "links": [
            {
                "path": link.relative_path,
                "target": link.raw_target,
                "resolved_target": link.resolved_target,
            }
            for link in snapshot.links
        ],
    }


def _same_link_topology(
    expected: tuple[_ArtifactLink, ...],
    actual: tuple[_ArtifactLink, ...],
) -> bool:
    return [
        (
            link.relative_path,
            link.raw_target,
            link.resolved_target,
            link.identity,
        )
        for link in expected
    ] == [
        (
            link.relative_path,
            link.raw_target,
            link.resolved_target,
            link.identity,
        )
        for link in actual
    ]


def _assert_same_snapshot(
    expected: _ArtifactSnapshot,
    actual: _ArtifactSnapshot,
    *,
    phase: str,
) -> None:
    if not _same_directory_identity(expected.root_identity, actual.root_identity):
        raise RuntimeError(f"macOS artifact root changed {phase}")
    if (
        expected.anchor_identity != actual.anchor_identity
        or expected.anchor_sha256 != actual.anchor_sha256
    ):
        raise RuntimeError(f"macOS artifact profile state changed {phase}")
    if expected.links != actual.links:
        raise RuntimeError(f"macOS artifact link closure changed {phase}")
    if len(expected.artifacts) != len(actual.artifacts):
        raise RuntimeError(f"macOS artifact closure changed {phase}")
    for expected_item, actual_item in zip(expected.artifacts, actual.artifacts):
        if (
            expected_item.relative_path != actual_item.relative_path
            or expected_item.identity != actual_item.identity
            or not _same_directory_identity(
                expected_item.parent_identity,
                actual_item.parent_identity,
            )
            or expected_item.sha256 != actual_item.sha256
        ):
            raise RuntimeError(f"macOS artifact closure changed {phase}")


def _stable_snapshot(
    root: Path,
    profile: str,
    anchor_path: Path | None,
    expected: _ArtifactSnapshot,
    *,
    phase: str,
    ignored_root: Path | None = None,
) -> _ArtifactSnapshot:
    first = _build_snapshot(root, profile, anchor_path, ignored_root=ignored_root)
    _assert_same_snapshot(expected, first, phase=phase)
    second = _build_snapshot(root, profile, anchor_path, ignored_root=ignored_root)
    _assert_same_snapshot(first, second, phase=f"during stable rescan {phase}")
    return second


def _create_staging_root(
    root: Path,
    root_identity: _PathIdentity,
    *,
    root_descriptor: int | None = None,
) -> tuple[Path, _PathIdentity]:
    if os.name == "nt":
        path = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
        return path, _assert_plain_directory(path, role="artifact staging root")

    owned_root_descriptor = root_descriptor is None
    if root_descriptor is None:
        root_descriptor = _open_validated_directory(
            root,
            root_identity,
            role="artifact root",
        )
    staging_descriptor: int | None = None
    try:
        for _attempt in range(128):
            name = STAGING_PREFIX + secrets.token_hex(12)
            try:
                os.mkdir(name, mode=0o700, dir_fd=root_descriptor)
            except FileExistsError:
                continue
            path = root / name
            identity = _identity_from_stat(
                os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
            )
            staging_descriptor = os.open(
                name,
                _directory_open_flags(),
                dir_fd=root_descriptor,
            )
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(staging_descriptor)),
                identity,
            ):
                raise RuntimeError("macOS artifact staging root identity changed")
            return path, identity
        raise RuntimeError("macOS artifact staging root allocation failed")
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        if owned_root_descriptor:
            os.close(root_descriptor)


def _assert_source(root: Path, artifact: _Artifact) -> None:
    _assert_parent_chain(root, artifact.path.parent)
    _assert_plain_directory(
        artifact.path.parent,
        role="artifact parent",
        expected_identity=artifact.parent_identity,
    )
    _assert_resolved_containment(artifact.path, root, role="native artifact")
    identity = _assert_plain_file(
        artifact.path,
        role="native artifact",
        expected_identity=artifact.identity,
    )
    if (
        _sha256_file(
            artifact.path,
            expected_identity=identity,
            role="native artifact",
        )
        != artifact.sha256
    ):
        raise RuntimeError("macOS native artifact content changed")


def _assert_staged(
    root: Path,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    staged: _StagedArtifact,
    *,
    verify_hash: bool = True,
) -> None:
    _assert_plain_directory(
        staging_root,
        role="artifact staging root",
        expected_identity=staging_root_identity,
    )
    _assert_resolved_containment(staging_root, root, role="artifact staging root")
    _assert_plain_directory(
        staged.path.parent,
        role="artifact staging directory",
        expected_identity=staged.parent_identity,
    )
    identity = _assert_plain_file(
        staged.path,
        role="staged native artifact",
        expected_identity=staged.identity,
    )
    _assert_resolved_containment(staged.path, staging_root, role="staged native artifact")
    if verify_hash and (
        _sha256_file(
            staged.path,
            expected_identity=identity,
            role="staged native artifact",
        )
        != staged.sha256
    ):
        raise RuntimeError("macOS staged native artifact content changed")


def _copy_to_staging(
    root: Path,
    artifact: _Artifact,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    index: int,
) -> _StagedArtifact:
    _assert_source(root, artifact)
    parent_name = f"{index:04d}"
    staging_parent = staging_root / parent_name
    staging_root_fd: int | None = None
    staging_parent_fd: int | None = None
    source_parent_fd: int | None = None
    source_fd: int | None = None
    target_fd: int | None = None
    try:
        if os.name == "nt":
            staging_parent.mkdir(mode=0o700)
        else:
            staging_root_fd = _open_validated_directory(
                staging_root,
                staging_root_identity,
                role="artifact staging root",
            )
            os.mkdir(parent_name, mode=0o700, dir_fd=staging_root_fd)
        parent_identity = _assert_plain_directory(
            staging_parent,
            role="artifact staging directory",
        )
        staged_path = staging_parent / artifact.path.name

        source_flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
        source_flags |= int(getattr(os, "O_BINARY", 0))
        source_flags |= int(getattr(os, "O_NOFOLLOW", 0))
        target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        target_flags |= int(getattr(os, "O_CLOEXEC", 0))
        target_flags |= int(getattr(os, "O_BINARY", 0))
        target_flags |= int(getattr(os, "O_NOFOLLOW", 0))
        if os.name == "nt":
            source_fd = os.open(artifact.path, source_flags)
            target_fd = os.open(staged_path, target_flags, 0o600)
        else:
            staging_parent_fd = os.open(
                parent_name,
                _directory_open_flags(),
                dir_fd=staging_root_fd,
            )
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(staging_parent_fd)),
                parent_identity,
            ):
                raise RuntimeError("macOS artifact staging directory changed")
            source_parent_fd = _open_validated_directory(
                artifact.path.parent,
                artifact.parent_identity,
                role="artifact parent",
            )
            source_fd = os.open(
                artifact.path.name,
                source_flags,
                dir_fd=source_parent_fd,
            )
            target_fd = os.open(
                staged_path.name,
                target_flags,
                0o600,
                dir_fd=staging_parent_fd,
            )

        source_stat = os.fstat(source_fd)
        if _identity_from_stat(source_stat) != artifact.identity:
            raise RuntimeError("macOS native artifact identity changed before staging")
        if hasattr(os, "fchmod"):
            os.fchmod(target_fd, stat.S_IMODE(source_stat.st_mode))
        digest = hashlib.sha256()
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(target_fd, remaining)
                if written <= 0:
                    raise OSError("failed to write staged native artifact")
                remaining = remaining[written:]
        os.fsync(target_fd)
        if digest.hexdigest() != artifact.sha256:
            raise RuntimeError("macOS native artifact content changed while staging")
        staged_identity = _identity_from_stat(os.fstat(target_fd))
        if not stat.S_ISREG(staged_identity.file_type) or staged_identity.link_count != 1:
            raise RuntimeError("macOS staged native artifact is not private")
    finally:
        for descriptor in (
            target_fd,
            source_fd,
            source_parent_fd,
            staging_parent_fd,
            staging_root_fd,
        ):
            if descriptor is not None:
                os.close(descriptor)

    staged = _StagedArtifact(
        source=artifact,
        path=staged_path,
        identity=staged_identity,
        parent_identity=parent_identity,
        sha256=artifact.sha256,
    )
    _assert_source(root, artifact)
    _assert_staged(root, staging_root, staging_root_identity, staged)
    return staged


def _run_command(
    command: list[str],
    *,
    action: str,
    run_command,
    path_prefixes: Mapping[str, object],
    allow_failure: bool = False,
    working_directory_fd: int | None = None,
) -> bool:
    try:
        result = run_bounded_subprocess(
            command,
            run_command=run_command,
            working_directory_fd=working_directory_fd,
            path_prefixes=path_prefixes,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"macOS artifact {action} timed out") from exc
    if result.returncode == 0:
        return True
    if allow_failure:
        return False
    detail = bounded_process_failure_detail(result, path_prefixes=path_prefixes)
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(f"macOS artifact {action} failed{suffix}")


def _sign_staged(
    root: Path,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    staged: _StagedArtifact,
    *,
    run_command,
    path_prefixes: Mapping[str, object],
) -> _StagedArtifact:
    _assert_source(root, staged.source)
    _assert_staged(root, staging_root, staging_root_identity, staged)
    staging_parent_fd: int | None = None
    try:
        command_path = str(staged.path)
        if os.name != "nt":
            staging_parent_fd = _open_validated_directory(
                staged.path.parent,
                staged.parent_identity,
                role="artifact staging directory",
            )
            command_path = staged.path.name
        _run_command(
            ["xattr", "-c", command_path],
            action="extended attribute cleanup",
            run_command=run_command,
            path_prefixes=path_prefixes,
            working_directory_fd=staging_parent_fd,
        )
        _assert_staged(root, staging_root, staging_root_identity, staged)
        _assert_source(root, staged.source)
        _run_command(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                command_path,
            ],
            action="signing",
            run_command=run_command,
            path_prefixes=path_prefixes,
            working_directory_fd=staging_parent_fd,
        )
        _assert_source(root, staged.source)
        signed_identity = _assert_plain_file(
            staged.path,
            role="staged native artifact",
        )
        signed = _StagedArtifact(
            source=staged.source,
            path=staged.path,
            identity=signed_identity,
            parent_identity=staged.parent_identity,
            sha256=_sha256_file(
                staged.path,
                expected_identity=signed_identity,
                role="staged native artifact",
            ),
        )
        _assert_staged(root, staging_root, staging_root_identity, signed)
        _run_command(
            ["codesign", "--verify", "--strict", "--verbose=2", command_path],
            action="staged verification",
            run_command=run_command,
            path_prefixes=path_prefixes,
            working_directory_fd=staging_parent_fd,
        )
        _assert_staged(root, staging_root, staging_root_identity, signed)
        _assert_source(root, signed.source)
        return signed
    finally:
        if staging_parent_fd is not None:
            os.close(staging_parent_fd)


def _replace_staged(
    root: Path,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    staged: _StagedArtifact,
) -> None:
    _assert_source(root, staged.source)
    _assert_staged(root, staging_root, staging_root_identity, staged)
    if os.name == "nt":
        os.replace(staged.path, staged.source.path)
        return

    staging_parent_fd = _open_validated_directory(
        staged.path.parent,
        staged.parent_identity,
        role="artifact staging directory",
    )
    target_parent_fd = _open_validated_directory(
        staged.source.path.parent,
        staged.source.parent_identity,
        role="artifact parent",
    )
    try:
        _assert_source(root, staged.source)
        _assert_staged(root, staging_root, staging_root_identity, staged)
        os.replace(
            staged.path.name,
            staged.source.path.name,
            src_dir_fd=staging_parent_fd,
            dst_dir_fd=target_parent_fd,
        )
    finally:
        os.close(target_parent_fd)
        os.close(staging_parent_fd)


def _load_stamp(
    stamp_path: Path | None,
    *,
    root_identity: _PathIdentity,
    root_descriptor: int | None,
    expected_identity: _PathIdentity | None = None,
) -> dict[str, object] | None:
    if stamp_path is None:
        return None
    return _load_codesign_state(
        stamp_path,
        expected_identity=expected_identity,
        parent_identity=root_identity,
        parent_descriptor=root_descriptor,
    )


def _verify_snapshot(
    root: Path,
    snapshot: _ArtifactSnapshot,
    *,
    run_command,
    path_prefixes: Mapping[str, object],
    allow_failure: bool,
) -> bool:
    for artifact in snapshot.artifacts:
        _assert_source(root, artifact)
        artifact_parent_fd: int | None = None
        try:
            command_path = str(artifact.path)
            if os.name != "nt":
                artifact_parent_fd = _open_validated_directory(
                    artifact.path.parent,
                    artifact.parent_identity,
                    role="artifact parent",
                )
                command_path = artifact.path.name
            if not _run_command(
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    "--verbose=2",
                    command_path,
                ],
                action="installed verification",
                run_command=run_command,
                path_prefixes=path_prefixes,
                allow_failure=allow_failure,
                working_directory_fd=artifact_parent_fd,
            ):
                return False
            _assert_source(root, artifact)
        finally:
            if artifact_parent_fd is not None:
                os.close(artifact_parent_fd)
    return True


def _assert_final_snapshot(
    original: _ArtifactSnapshot,
    signed: list[_StagedArtifact],
    actual: _ArtifactSnapshot,
) -> None:
    if not _same_directory_identity(original.root_identity, actual.root_identity):
        raise RuntimeError("macOS artifact root changed while installing signatures")
    if (
        original.anchor_identity != actual.anchor_identity
        or original.anchor_sha256 != actual.anchor_sha256
    ):
        raise RuntimeError("macOS artifact profile state changed while installing signatures")
    if not _same_link_topology(original.links, actual.links):
        raise RuntimeError("macOS artifact link closure changed while installing signatures")
    expected = [(item.source.relative_path, item.sha256) for item in signed]
    observed = [(item.relative_path, item.sha256) for item in actual.artifacts]
    if expected != observed:
        raise RuntimeError("macOS artifact closure changed while installing signatures")


def sign_macos_artifacts(
    *,
    project_root: str | Path,
    root: str | Path,
    profile: str,
    stamp_path: str | Path | None = None,
    run_command=subprocess.run,
    system_name: str | None = None,
    force: bool = False,
) -> MacOSArtifactSigningOutcome:
    resolved_system = platform.system() if system_name is None else system_name
    if resolved_system != "Darwin":
        return MacOSArtifactSigningOutcome(reused=False, artifact_count=0, skipped=True)

    resolved_project = _absolute_path(project_root)
    resolved_root = _absolute_path(root)
    resolved_stamp = _absolute_path(stamp_path) if stamp_path is not None else None
    anchor_path, _expected_stamp = _validate_profile_paths(
        resolved_project,
        resolved_root,
        profile,
        resolved_stamp,
    )
    path_prefixes = {
        "<ARTIFACT_ROOT>": resolved_root,
        "<PROJECT_ROOT>": resolved_project,
        "<USER_HOME>": Path.home(),
    }
    snapshot = _build_snapshot(resolved_root, profile, anchor_path)
    state = _snapshot_state(profile, snapshot)
    root_descriptor: int | None = None
    if os.name != "nt":
        root_descriptor = _open_validated_directory(
            resolved_root,
            snapshot.root_identity,
            role="artifact root",
        )

    try:
        stamp_identity = (
            _stamp_entry_identity(
                resolved_stamp,
                parent_identity=snapshot.root_identity,
                parent_descriptor=root_descriptor,
            )
            if resolved_stamp is not None
            else None
        )
        stored_state = _load_stamp(
            resolved_stamp,
            root_identity=snapshot.root_identity,
            root_descriptor=root_descriptor,
            expected_identity=stamp_identity,
        )
        if not force and resolved_stamp is not None and stored_state == state:
            if _verify_snapshot(
                resolved_root,
                snapshot,
                run_command=run_command,
                path_prefixes=path_prefixes,
                allow_failure=True,
            ):
                confirmed = _stable_snapshot(
                    resolved_root,
                    profile,
                    anchor_path,
                    snapshot,
                    phase="during cached verification",
                )
                if _load_stamp(
                    resolved_stamp,
                    root_identity=snapshot.root_identity,
                    root_descriptor=root_descriptor,
                    expected_identity=stamp_identity,
                ) != _snapshot_state(profile, confirmed):
                    raise RuntimeError(
                        "macOS artifact signature stamp changed during verification"
                    )
                return MacOSArtifactSigningOutcome(
                    reused=True,
                    artifact_count=len(confirmed.artifacts),
                )

        if resolved_stamp is not None:
            _unlink_codesign_stamp(
                resolved_stamp,
                parent_identity=snapshot.root_identity,
                parent_descriptor=root_descriptor,
            )
        snapshot = _stable_snapshot(
            resolved_root,
            profile,
            anchor_path,
            snapshot,
            phase="before staging",
        )
        staging_root, staging_root_identity = _create_staging_root(
            resolved_root,
            snapshot.root_identity,
            root_descriptor=root_descriptor,
        )
        try:
            staged = [
                _copy_to_staging(
                    resolved_root,
                    artifact,
                    staging_root,
                    staging_root_identity,
                    index,
                )
                for index, artifact in enumerate(snapshot.artifacts)
            ]
            signed = [
                _sign_staged(
                    resolved_root,
                    staging_root,
                    staging_root_identity,
                    item,
                    run_command=run_command,
                    path_prefixes=path_prefixes,
                )
                for item in staged
            ]
            snapshot = _stable_snapshot(
                resolved_root,
                profile,
                anchor_path,
                snapshot,
                phase="while signing private copies",
                ignored_root=staging_root,
            )
            for item in signed:
                _replace_staged(
                    resolved_root,
                    staging_root,
                    staging_root_identity,
                    item,
                )
            installed = _build_snapshot(
                resolved_root,
                profile,
                anchor_path,
                ignored_root=staging_root,
            )
            _assert_final_snapshot(snapshot, signed, installed)
            _verify_snapshot(
                resolved_root,
                installed,
                run_command=run_command,
                path_prefixes=path_prefixes,
                allow_failure=False,
            )
            confirmed = _stable_snapshot(
                resolved_root,
                profile,
                anchor_path,
                installed,
                phase="during installed verification",
                ignored_root=staging_root,
            )
            if resolved_stamp is not None:
                write_macos_backend_codesign_state(
                    resolved_stamp,
                    _snapshot_state(profile, confirmed),
                    parent_identity=snapshot.root_identity,
                    parent_descriptor=root_descriptor,
                )
                written_stamp_identity = _stamp_entry_identity(
                    resolved_stamp,
                    parent_identity=snapshot.root_identity,
                    parent_descriptor=root_descriptor,
                )
                if written_stamp_identity is None:
                    raise RuntimeError("macOS artifact signature stamp is unavailable")
                confirmed = _stable_snapshot(
                    resolved_root,
                    profile,
                    anchor_path,
                    confirmed,
                    phase="while writing signature stamp",
                    ignored_root=staging_root,
                )
                if _load_stamp(
                    resolved_stamp,
                    root_identity=snapshot.root_identity,
                    root_descriptor=root_descriptor,
                    expected_identity=written_stamp_identity,
                ) != _snapshot_state(profile, confirmed):
                    raise RuntimeError("macOS artifact signature stamp write was unstable")
            return MacOSArtifactSigningOutcome(
                reused=False,
                artifact_count=len(confirmed.artifacts),
            )
        finally:
            _cleanup_private_staging_root(
                resolved_root,
                snapshot.root_identity,
                staging_root,
                staging_root_identity,
                venv_descriptor=root_descriptor,
            )
    except BaseException:
        if resolved_stamp is not None:
            _unlink_codesign_stamp(
                resolved_stamp,
                parent_identity=snapshot.root_identity,
                parent_descriptor=root_descriptor,
                suppress_errors=True,
            )
        raise
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--profile",
        required=True,
        choices=("frontend", "backend-bundle"),
    )
    parser.add_argument("--stamp")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path_prefixes = {
        "<PROJECT_ROOT>": _absolute_path(args.project_root),
        "<ARTIFACT_ROOT>": _absolute_path(args.root),
        "<USER_HOME>": Path.home(),
    }
    error_prefix = "macOS artifact signing failed"
    try:
        outcome = sign_macos_artifacts(
            project_root=args.project_root,
            root=args.root,
            profile=args.profile,
            stamp_path=args.stamp,
            force=args.force,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        emitter = BoundedTextEmitter(
            limit_bytes=(
                DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES
                - len(error_prefix.encode("utf-8"))
                - len(": \n".encode("utf-8"))
            ),
            path_prefixes=path_prefixes,
        )
        detail = emitter.filter(str(exc)).strip()
        suffix = f": {detail}" if detail else ""
        print(f"{error_prefix}{suffix}", file=sys.stderr)
        return 1
    if outcome.skipped:
        print("macOS artifact signing skipped on this platform")
    elif outcome.reused:
        print(f"macOS artifact signatures verified ({outcome.artifact_count} files)")
    else:
        print(f"macOS artifact signatures refreshed ({outcome.artifact_count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
