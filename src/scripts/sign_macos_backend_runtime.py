from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Mapping


def _ensure_project_root_on_sys_path(
    script_path: str | Path | None = None,
) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.backend_environment_state import BACKEND_ENVIRONMENT_STATE_NAME
from src.core.backend_runtime_lock import (
    DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    backend_runtime_lock,
)
from src.utils.subprocess_safety import (
    bounded_process_failure_detail,
    run_bounded_subprocess,
)


BACKEND_RUNTIME_VENV_NAME = ".venv-backend-runtime-gpu"
MACOS_BACKEND_CODESIGN_STAMP_NAME = ".macos-native-codesign.sha256"
MACOS_BACKEND_CODESIGN_STATE_SCHEMA_VERSION = 1
NATIVE_LIBRARY_SUFFIXES = (".dylib", ".so")


@dataclass(frozen=True)
class MacOSBackendSigningOutcome:
    reused: bool
    library_count: int
    skipped: bool = False


@dataclass(frozen=True)
class _PathIdentity:
    device: int
    inode: int
    file_type: int
    file_attributes: int
    link_count: int


@dataclass(frozen=True)
class _NativeLibrary:
    path: Path
    identity: _PathIdentity
    parent_identity: _PathIdentity


@dataclass(frozen=True)
class _StagedNativeLibrary:
    source: _NativeLibrary
    path: Path
    identity: _PathIdentity
    parent_identity: _PathIdentity


@dataclass(frozen=True)
class _SigningSnapshot:
    venv_identity: _PathIdentity
    library_root_identity: _PathIdentity
    state_identity: _PathIdentity
    libraries: tuple[_NativeLibrary, ...]


def _path_identity(path: Path, *, follow_symlinks: bool = False) -> _PathIdentity:
    path_stat = path.stat() if follow_symlinks else path.lstat()
    return _identity_from_stat(path_stat)


def _identity_from_stat(path_stat) -> _PathIdentity:
    return _PathIdentity(
        device=int(path_stat.st_dev),
        inode=int(path_stat.st_ino),
        file_type=stat.S_IFMT(path_stat.st_mode),
        file_attributes=int(getattr(path_stat, "st_file_attributes", 0)),
        link_count=int(path_stat.st_nlink),
    )


def _identity_is_reparse(identity: _PathIdentity) -> bool:
    return bool(identity.file_attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _identity_is_link(identity: _PathIdentity) -> bool:
    return stat.S_ISLNK(identity.file_type) or _identity_is_reparse(identity)


def _same_directory_identity(
    left: _PathIdentity,
    right: _PathIdentity,
) -> bool:
    return (
        left.device == right.device
        and left.inode == right.inode
        and left.file_type == right.file_type
        and left.file_attributes == right.file_attributes
    )


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_plain_directory(
    path: Path,
    *,
    role: str,
    expected_identity: _PathIdentity | None = None,
) -> _PathIdentity:
    try:
        identity = _path_identity(path)
    except OSError as exc:
        raise RuntimeError(f"macOS backend {role} identity is unavailable") from exc
    if _identity_is_link(identity):
        raise ValueError(f"macOS backend {role} must not be a link or reparse point")
    if not stat.S_ISDIR(identity.file_type):
        raise ValueError(f"macOS backend {role} must be a directory")
    if expected_identity is not None and not _same_directory_identity(
        identity,
        expected_identity,
    ):
        raise RuntimeError(f"macOS backend {role} identity changed")
    return identity


def _assert_plain_file(
    path: Path,
    *,
    role: str,
    expected_identity: _PathIdentity | None = None,
) -> _PathIdentity:
    try:
        identity = _path_identity(path)
    except OSError as exc:
        raise RuntimeError(f"macOS backend {role} identity is unavailable") from exc
    if _identity_is_link(identity):
        raise ValueError(f"macOS backend {role} must not be a link or reparse point")
    if not stat.S_ISREG(identity.file_type):
        raise ValueError(f"macOS backend {role} must be a regular file")
    if identity.link_count != 1:
        raise ValueError(f"macOS backend {role} must not be a hard link")
    if expected_identity is not None and identity != expected_identity:
        raise RuntimeError(f"macOS backend {role} identity changed")
    return identity


def _assert_resolved_containment(path: Path, parent: Path, *, role: str) -> None:
    try:
        resolved_path = path.resolve(strict=True)
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"macOS backend {role} containment is unavailable") from exc
    if not _path_is_within(resolved_path, resolved_parent):
        raise ValueError(f"macOS backend {role} escaped the dedicated runtime")


def _assert_snapshot_roots(venv: Path, snapshot: _SigningSnapshot) -> None:
    _assert_plain_directory(
        venv,
        role="runtime root",
        expected_identity=snapshot.venv_identity,
    )
    _assert_plain_directory(
        venv / "lib",
        role="library root",
        expected_identity=snapshot.library_root_identity,
    )
    _assert_resolved_containment(venv / "lib", venv, role="library root")


def _assert_native_library(
    venv: Path,
    library: _NativeLibrary,
) -> _PathIdentity:
    _assert_resolved_containment(
        library.path.parent,
        venv / "lib",
        role="native library parent",
    )
    _assert_plain_directory(
        library.path.parent,
        role="native library parent",
        expected_identity=library.parent_identity,
    )
    _assert_resolved_containment(library.path, venv / "lib", role="native library")
    return _assert_plain_file(
        library.path,
        role="native library",
        expected_identity=library.identity,
    )


def _sha256_file(
    path: Path,
    *,
    expected_identity: _PathIdentity | None = None,
    role: str = "file",
) -> str:
    identity = _assert_plain_file(
        path,
        role=role,
        expected_identity=expected_identity,
    )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened_identity = _identity_from_stat(os.fstat(handle.fileno()))
        if opened_identity != identity:
            raise RuntimeError(f"macOS backend {role} identity changed before hashing")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        final_identity = _identity_from_stat(os.fstat(handle.fileno()))
        if final_identity != identity:
            raise RuntimeError(f"macOS backend {role} identity changed while hashing")
    _assert_plain_file(path, role=role, expected_identity=identity)
    return digest.hexdigest()


def _native_library_records(venv: Path) -> tuple[_NativeLibrary, ...]:
    library_root = venv / "lib"
    _assert_plain_directory(venv, role="runtime root")
    _assert_plain_directory(library_root, role="library root")
    _assert_resolved_containment(library_root, venv, role="library root")

    libraries: list[_NativeLibrary] = []
    pending = [library_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                identity = _path_identity(path)
                if _identity_is_link(identity):
                    role = (
                        "native library"
                        if path.suffix.lower() in NATIVE_LIBRARY_SUFFIXES
                        else "library tree entry"
                    )
                    raise ValueError(
                        f"macOS backend {role} must not be a link or reparse point"
                    )
                if stat.S_ISDIR(identity.file_type):
                    _assert_resolved_containment(path, library_root, role="library directory")
                    pending.append(path)
                elif (
                    stat.S_ISREG(identity.file_type)
                    and path.suffix.lower() in NATIVE_LIBRARY_SUFFIXES
                ):
                    _assert_resolved_containment(path, library_root, role="native library")
                    _assert_plain_file(
                        path,
                        role="native library",
                        expected_identity=identity,
                    )
                    parent_identity = _assert_plain_directory(
                        path.parent,
                        role="native library parent",
                    )
                    libraries.append(
                        _NativeLibrary(
                            path=path,
                            identity=identity,
                            parent_identity=parent_identity,
                        )
                    )
    return tuple(
        sorted(
            libraries,
            key=lambda library: library.path.relative_to(venv).as_posix(),
        )
    )


def _native_library_paths(venv: Path) -> list[Path]:
    return [library.path for library in _native_library_records(venv)]


def _build_signing_snapshot(venv: Path, state_path: Path) -> _SigningSnapshot:
    venv_identity = _assert_plain_directory(venv, role="runtime root")
    library_root_identity = _assert_plain_directory(
        venv / "lib",
        role="library root",
    )
    state_identity = _assert_plain_file(state_path, role="environment state")
    _assert_resolved_containment(state_path, venv, role="environment state")
    libraries = _native_library_records(venv)
    snapshot = _SigningSnapshot(
        venv_identity=venv_identity,
        library_root_identity=library_root_identity,
        state_identity=state_identity,
        libraries=libraries,
    )
    _assert_snapshot_roots(venv, snapshot)
    return snapshot


def _codesign_state_from_snapshot(
    venv: Path,
    state_path: Path,
    snapshot: _SigningSnapshot,
) -> dict[str, object]:
    _assert_snapshot_roots(venv, snapshot)
    _assert_plain_file(
        state_path,
        role="environment state",
        expected_identity=snapshot.state_identity,
    )
    libraries = []
    for library in snapshot.libraries:
        _assert_snapshot_roots(venv, snapshot)
        _assert_native_library(venv, library)
        library_stat = library.path.stat()
        libraries.append(
            {
                "path": library.path.relative_to(venv).as_posix(),
                "size": int(library_stat.st_size),
                "sha256": _sha256_file(
                    library.path,
                    expected_identity=library.identity,
                    role="native library",
                ),
            }
        )
        _assert_snapshot_roots(venv, snapshot)
    _assert_snapshot_roots(venv, snapshot)
    state_sha256 = _sha256_file(
        state_path,
        expected_identity=snapshot.state_identity,
        role="environment state",
    )
    _assert_snapshot_roots(venv, snapshot)
    return {
        "schema_version": MACOS_BACKEND_CODESIGN_STATE_SCHEMA_VERSION,
        "backend_environment_state_sha256": state_sha256,
        "native_libraries": libraries,
    }


def _assert_equivalent_snapshot(
    expected: _SigningSnapshot,
    actual: _SigningSnapshot,
    *,
    phase: str,
) -> None:
    if (
        not _same_directory_identity(
            actual.venv_identity,
            expected.venv_identity,
        )
        or not _same_directory_identity(
            actual.library_root_identity,
            expected.library_root_identity,
        )
        or actual.state_identity != expected.state_identity
    ):
        raise RuntimeError(f"macOS backend signing inputs changed {phase}")
    expected_paths = [library.path for library in expected.libraries]
    actual_paths = [library.path for library in actual.libraries]
    if actual_paths != expected_paths:
        raise RuntimeError(f"macOS backend native library closure changed {phase}")
    if any(
        (
            actual_library.identity != expected_library.identity
            or not _same_directory_identity(
                actual_library.parent_identity,
                expected_library.parent_identity,
            )
        )
        for expected_library, actual_library in zip(
            expected.libraries,
            actual.libraries,
            strict=True,
        )
    ):
        raise RuntimeError(f"macOS backend native library identity changed {phase}")


def _stable_rescan(
    venv: Path,
    state_path: Path,
    *,
    expected_snapshot: _SigningSnapshot,
    expected_state: Mapping[str, object],
    phase: str,
) -> tuple[_SigningSnapshot, dict[str, object]]:
    rescanned_snapshot = _build_signing_snapshot(venv, state_path)
    _assert_equivalent_snapshot(
        expected_snapshot,
        rescanned_snapshot,
        phase=phase,
    )
    rescanned_state = _codesign_state_from_snapshot(
        venv,
        state_path,
        rescanned_snapshot,
    )
    if rescanned_state != dict(expected_state):
        raise RuntimeError(f"macOS backend signing input content changed {phase}")

    confirmed_snapshot = _build_signing_snapshot(venv, state_path)
    _assert_equivalent_snapshot(
        rescanned_snapshot,
        confirmed_snapshot,
        phase=f"during stable rescan {phase}",
    )
    confirmed_state = _codesign_state_from_snapshot(
        venv,
        state_path,
        confirmed_snapshot,
    )
    if confirmed_state != rescanned_state:
        raise RuntimeError(
            f"macOS backend signing input content changed during stable rescan {phase}"
        )
    return confirmed_snapshot, confirmed_state


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_DIRECTORY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    return flags


def _open_validated_directory(
    path: Path,
    expected_identity: _PathIdentity,
    *,
    role: str,
) -> int:
    descriptor = os.open(path, _directory_open_flags())
    try:
        if not _same_directory_identity(
            _identity_from_stat(os.fstat(descriptor)),
            expected_identity,
        ):
            raise RuntimeError(f"macOS backend {role} identity changed while opening")
        _assert_plain_directory(
            path,
            role=role,
            expected_identity=expected_identity,
        )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _remove_directory_contents_by_fd(directory_descriptor: int) -> None:
    with os.scandir(directory_descriptor) as entries:
        for entry in entries:
            entry_identity = _identity_from_stat(entry.stat(follow_symlinks=False))
            if stat.S_ISDIR(entry_identity.file_type) and not _identity_is_link(
                entry_identity
            ):
                child_descriptor = os.open(
                    entry.name,
                    _directory_open_flags(),
                    dir_fd=directory_descriptor,
                )
                try:
                    if not _same_directory_identity(
                        _identity_from_stat(os.fstat(child_descriptor)),
                        entry_identity,
                    ):
                        raise RuntimeError(
                            "macOS backend staging cleanup directory identity changed"
                        )
                    _remove_directory_contents_by_fd(child_descriptor)
                finally:
                    os.close(child_descriptor)
                os.rmdir(entry.name, dir_fd=directory_descriptor)
            else:
                os.unlink(entry.name, dir_fd=directory_descriptor)


def _cleanup_private_staging_root(
    venv: Path,
    venv_identity: _PathIdentity,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    *,
    venv_descriptor: int | None = None,
) -> None:
    try:
        if staging_root.parent != venv:
            return
        if os.name == "nt":
            actual_identity = _assert_plain_directory(
                staging_root,
                role="codesign staging root",
            )
            if not _same_directory_identity(
                actual_identity,
                staging_root_identity,
            ):
                return
            _assert_resolved_containment(
                staging_root,
                venv,
                role="codesign staging root",
            )
            shutil.rmtree(staging_root)
            return

        owned_venv_descriptor = venv_descriptor is None
        if venv_descriptor is None:
            venv_descriptor = _open_validated_directory(
                venv,
                venv_identity,
                role="runtime root",
            )
        staging_descriptor: int | None = None
        try:
            staging_descriptor = os.open(
                staging_root.name,
                _directory_open_flags(),
                dir_fd=venv_descriptor,
            )
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(staging_descriptor)),
                staging_root_identity,
            ):
                return
            _remove_directory_contents_by_fd(staging_descriptor)
            current_identity = _identity_from_stat(
                os.stat(
                    staging_root.name,
                    dir_fd=venv_descriptor,
                    follow_symlinks=False,
                )
            )
            if _same_directory_identity(current_identity, staging_root_identity):
                os.rmdir(staging_root.name, dir_fd=venv_descriptor)
        finally:
            if staging_descriptor is not None:
                os.close(staging_descriptor)
            if owned_venv_descriptor:
                os.close(venv_descriptor)
    except (OSError, RuntimeError, ValueError):
        return


def _create_private_staging_root(
    venv: Path,
    snapshot: _SigningSnapshot,
    *,
    venv_descriptor: int | None = None,
) -> tuple[Path, _PathIdentity]:
    _assert_snapshot_roots(venv, snapshot)
    provided_venv_descriptor = venv_descriptor
    staging_root: Path | None = None
    identity: _PathIdentity | None = None
    try:
        if os.name == "nt":
            staging_root = Path(
                tempfile.mkdtemp(prefix=".vantage-codesign-staging-", dir=venv)
            )
            identity = _assert_plain_directory(
                staging_root,
                role="codesign staging root",
            )
        else:
            owned_venv_descriptor = venv_descriptor is None
            if venv_descriptor is None:
                venv_descriptor = _open_validated_directory(
                    venv,
                    snapshot.venv_identity,
                    role="runtime root",
                )
            staging_descriptor: int | None = None
            try:
                for _attempt in range(128):
                    staging_name = (
                        ".vantage-codesign-staging-" + secrets.token_hex(12)
                    )
                    try:
                        os.mkdir(staging_name, mode=0o700, dir_fd=venv_descriptor)
                    except FileExistsError:
                        continue
                    staging_root = venv / staging_name
                    identity = _identity_from_stat(
                        os.stat(
                            staging_name,
                            dir_fd=venv_descriptor,
                            follow_symlinks=False,
                        )
                    )
                    if _identity_is_link(identity) or not stat.S_ISDIR(
                        identity.file_type
                    ):
                        raise RuntimeError(
                            "macOS backend codesign staging root is not private"
                        )
                    staging_descriptor = os.open(
                        staging_name,
                        _directory_open_flags(),
                        dir_fd=venv_descriptor,
                    )
                    if not _same_directory_identity(
                        _identity_from_stat(os.fstat(staging_descriptor)),
                        identity,
                    ):
                        raise RuntimeError(
                            "macOS backend codesign staging root identity changed"
                        )
                    break
                else:
                    raise RuntimeError(
                        "macOS backend could not allocate a private staging root"
                    )
            finally:
                if staging_descriptor is not None:
                    os.close(staging_descriptor)
                if owned_venv_descriptor:
                    os.close(venv_descriptor)

        if staging_root is None or identity is None:
            raise RuntimeError("macOS backend codesign staging root is unavailable")
        _assert_plain_directory(
            staging_root,
            role="codesign staging root",
            expected_identity=identity,
        )
        _assert_resolved_containment(
            staging_root,
            venv,
            role="codesign staging root",
        )
        _assert_snapshot_roots(venv, snapshot)
        return staging_root, identity
    except BaseException:
        if staging_root is not None and identity is not None:
            _cleanup_private_staging_root(
                venv,
                snapshot.venv_identity,
                staging_root,
                identity,
                venv_descriptor=provided_venv_descriptor,
            )
        raise


def _assert_staged_library(
    venv: Path,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    staged: _StagedNativeLibrary,
) -> _PathIdentity:
    _assert_plain_directory(
        staging_root,
        role="codesign staging root",
        expected_identity=staging_root_identity,
    )
    _assert_resolved_containment(
        staging_root,
        venv,
        role="codesign staging root",
    )
    _assert_plain_directory(
        staged.path.parent,
        role="codesign staging directory",
        expected_identity=staged.parent_identity,
    )
    _assert_resolved_containment(
        staged.path.parent,
        staging_root,
        role="codesign staging directory",
    )
    _assert_resolved_containment(
        staged.path,
        staging_root,
        role="staged native library",
    )
    return _assert_plain_file(
        staged.path,
        role="staged native library",
        expected_identity=staged.identity,
    )


def _copy_native_library_to_staging(
    venv: Path,
    snapshot: _SigningSnapshot,
    library: _NativeLibrary,
    *,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
    index: int,
    expected_sha256: str,
) -> _StagedNativeLibrary:
    _assert_snapshot_roots(venv, snapshot)
    _assert_native_library(venv, library)
    _assert_plain_directory(
        staging_root,
        role="codesign staging root",
        expected_identity=staging_root_identity,
    )
    staging_parent_name = f"{index:04d}"
    staging_parent = staging_root / staging_parent_name
    staging_root_descriptor: int | None = None
    staging_parent_descriptor: int | None = None
    source_parent_descriptor: int | None = None
    source_descriptor: int | None = None
    target_descriptor: int | None = None
    parent_identity: _PathIdentity | None = None
    staged_identity: _PathIdentity | None = None
    staged_path = staging_parent / library.path.name
    try:
        if os.name == "nt":
            staging_parent.mkdir(mode=0o700)
        else:
            staging_root_descriptor = _open_validated_directory(
                staging_root,
                staging_root_identity,
                role="codesign staging root",
            )
            os.mkdir(
                staging_parent_name,
                mode=0o700,
                dir_fd=staging_root_descriptor,
            )
        parent_identity = _assert_plain_directory(
            staging_parent,
            role="codesign staging directory",
        )
        _assert_resolved_containment(
            staging_parent,
            staging_root,
            role="codesign staging directory",
        )

        source_flags = os.O_RDONLY
        source_flags |= int(getattr(os, "O_CLOEXEC", 0))
        source_flags |= int(getattr(os, "O_BINARY", 0))
        source_flags |= int(getattr(os, "O_NOFOLLOW", 0))
        target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        target_flags |= int(getattr(os, "O_CLOEXEC", 0))
        target_flags |= int(getattr(os, "O_BINARY", 0))
        target_flags |= int(getattr(os, "O_NOFOLLOW", 0))

        if os.name == "nt":
            source_descriptor = os.open(library.path, source_flags)
        else:
            staging_parent_descriptor = os.open(
                staging_parent_name,
                _directory_open_flags(),
                dir_fd=staging_root_descriptor,
            )
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(staging_parent_descriptor)),
                parent_identity,
            ):
                raise RuntimeError(
                    "macOS backend codesign staging directory identity changed"
                )
            source_parent_descriptor = _open_validated_directory(
                library.path.parent,
                library.parent_identity,
                role="native library parent",
            )
            source_descriptor = os.open(
                library.path.name,
                source_flags,
                dir_fd=source_parent_descriptor,
            )
        source_stat = os.fstat(source_descriptor)
        source_identity = _identity_from_stat(source_stat)
        if source_identity != library.identity:
            raise RuntimeError(
                "macOS backend native library identity changed before staging"
            )
        _assert_plain_file(
            library.path,
            role="native library",
            expected_identity=source_identity,
        )

        if os.name == "nt":
            target_descriptor = os.open(staged_path, target_flags, 0o600)
        else:
            target_descriptor = os.open(
                staged_path.name,
                target_flags,
                0o600,
                dir_fd=staging_parent_descriptor,
            )
        if hasattr(os, "fchmod"):
            os.fchmod(target_descriptor, stat.S_IMODE(source_stat.st_mode))
        digest = hashlib.sha256()
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(target_descriptor, remaining)
                if written <= 0:
                    raise OSError("failed to write staged native library")
                remaining = remaining[written:]
        os.fsync(target_descriptor)
        staged_identity = _identity_from_stat(os.fstat(target_descriptor))
        if (
            not stat.S_ISREG(staged_identity.file_type)
            or staged_identity.link_count != 1
        ):
            raise RuntimeError(
                "macOS backend staged native library is not a private file"
            )
        if _identity_from_stat(os.fstat(source_descriptor)) != source_identity:
            raise RuntimeError(
                "macOS backend native library identity changed while staging"
            )
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError(
                "macOS backend native library content changed while staging"
            )
    finally:
        if target_descriptor is not None:
            os.close(target_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)
        if source_parent_descriptor is not None:
            os.close(source_parent_descriptor)
        if staging_parent_descriptor is not None:
            os.close(staging_parent_descriptor)
        if staging_root_descriptor is not None:
            os.close(staging_root_descriptor)

    if parent_identity is None or staged_identity is None:
        raise RuntimeError("macOS backend staged native library is unavailable")

    _assert_native_library(venv, library)
    staged = _StagedNativeLibrary(
        source=library,
        path=staged_path,
        identity=staged_identity,
        parent_identity=parent_identity,
    )
    _assert_staged_library(
        venv,
        staging_root,
        staging_root_identity,
        staged,
    )
    if (
        _sha256_file(
            staged.path,
            expected_identity=staged.identity,
            role="staged native library",
        )
        != expected_sha256
    ):
        raise RuntimeError(
            "macOS backend staged native library content does not match source state"
        )
    return staged


def _replace_staged_native_library(
    venv: Path,
    snapshot: _SigningSnapshot,
    staged: _StagedNativeLibrary,
    *,
    staging_root: Path,
    staging_root_identity: _PathIdentity,
) -> _NativeLibrary:
    _assert_snapshot_roots(venv, snapshot)
    _assert_native_library(venv, staged.source)
    _assert_staged_library(
        venv,
        staging_root,
        staging_root_identity,
        staged,
    )

    if os.name == "nt":
        os.replace(staged.path, staged.source.path)
    else:
        directory_flags = os.O_RDONLY
        directory_flags |= int(getattr(os, "O_CLOEXEC", 0))
        directory_flags |= int(getattr(os, "O_DIRECTORY", 0))
        directory_flags |= int(getattr(os, "O_NOFOLLOW", 0))
        staging_parent_descriptor = os.open(staged.path.parent, directory_flags)
        target_parent_descriptor = os.open(
            staged.source.path.parent,
            directory_flags,
        )
        try:
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(staging_parent_descriptor)),
                staged.parent_identity,
            ):
                raise RuntimeError(
                    "macOS backend codesign staging directory identity changed"
                )
            if not _same_directory_identity(
                _identity_from_stat(os.fstat(target_parent_descriptor)),
                staged.source.parent_identity,
            ):
                raise RuntimeError(
                    "macOS backend native library parent identity changed"
                )
            _assert_native_library(venv, staged.source)
            _assert_staged_library(
                venv,
                staging_root,
                staging_root_identity,
                staged,
            )
            os.replace(
                staged.path.name,
                staged.source.path.name,
                src_dir_fd=staging_parent_descriptor,
                dst_dir_fd=target_parent_descriptor,
            )
        finally:
            os.close(staging_parent_descriptor)
            os.close(target_parent_descriptor)

    _assert_plain_directory(
        staged.source.path.parent,
        role="native library parent",
        expected_identity=staged.source.parent_identity,
    )
    _assert_resolved_containment(
        staged.source.path,
        venv / "lib",
        role="native library",
    )
    signed_identity = _assert_plain_file(
        staged.source.path,
        role="native library",
    )
    return _NativeLibrary(
        path=staged.source.path,
        identity=signed_identity,
        parent_identity=staged.source.parent_identity,
    )


def build_macos_backend_codesign_state(
    venv: str | Path,
    state_path: str | Path,
) -> dict[str, object]:
    resolved_venv = Path(venv)
    resolved_state_path = Path(state_path)
    snapshot = _build_signing_snapshot(resolved_venv, resolved_state_path)
    return _codesign_state_from_snapshot(
        resolved_venv,
        resolved_state_path,
        snapshot,
    )


def write_macos_backend_codesign_state(
    stamp_path: str | Path,
    state: Mapping[str, object],
    *,
    replace_file: Callable[..., object] = os.replace,
    parent_identity: _PathIdentity | None = None,
    parent_descriptor: int | None = None,
) -> Path:
    resolved_stamp_path = Path(stamp_path)
    stamp_parent = resolved_stamp_path.parent
    if parent_identity is None:
        stamp_parent.mkdir(parents=True, exist_ok=True)
        parent_identity = _assert_plain_directory(
            stamp_parent,
            role="signature stamp parent",
        )
    payload = json.dumps(
        dict(state),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"

    if os.name != "nt":
        owned_parent_descriptor = parent_descriptor is None
        if parent_descriptor is None:
            parent_descriptor = _open_validated_directory(
                stamp_parent,
                parent_identity,
                role="signature stamp parent",
            )
        temporary_name: str | None = None
        temporary_identity: _PathIdentity | None = None
        temporary_descriptor: int | None = None
        try:
            _assert_stamp_parent(
                stamp_parent,
                parent_identity,
                parent_descriptor,
            )
            _stamp_entry_identity(
                resolved_stamp_path,
                parent_identity=parent_identity,
                parent_descriptor=parent_descriptor,
            )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= int(getattr(os, "O_CLOEXEC", 0))
            flags |= int(getattr(os, "O_NOFOLLOW", 0))
            for _attempt in range(128):
                candidate = (
                    f".{resolved_stamp_path.name}.{secrets.token_hex(12)}.tmp"
                )
                try:
                    temporary_descriptor = os.open(
                        candidate,
                        flags,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                except FileExistsError:
                    continue
                temporary_name = candidate
                break
            else:
                raise RuntimeError(
                    "macOS backend could not allocate a private signature stamp"
                )

            temporary_identity = _identity_from_stat(
                os.fstat(temporary_descriptor)
            )
            if (
                not stat.S_ISREG(temporary_identity.file_type)
                or temporary_identity.link_count != 1
            ):
                raise RuntimeError(
                    "macOS backend temporary signature stamp is not a private file"
                )
            encoded_payload = payload.encode("utf-8")
            remaining = memoryview(encoded_payload)
            while remaining:
                written = os.write(temporary_descriptor, remaining)
                if written <= 0:
                    raise OSError("failed to write macOS backend signature stamp")
                remaining = remaining[written:]
            os.fsync(temporary_descriptor)
            if _identity_from_stat(os.fstat(temporary_descriptor)) != temporary_identity:
                raise RuntimeError(
                    "macOS backend temporary signature stamp identity changed"
                )
            os.close(temporary_descriptor)
            temporary_descriptor = None

            _assert_stamp_parent(
                stamp_parent,
                parent_identity,
                parent_descriptor,
            )
            replace_file(
                temporary_name,
                resolved_stamp_path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            written_identity = _stamp_entry_identity(
                resolved_stamp_path,
                parent_identity=parent_identity,
                parent_descriptor=parent_descriptor,
            )
            if written_identity != temporary_identity:
                raise RuntimeError(
                    "macOS backend signature stamp identity changed during replace"
                )
            _assert_stamp_parent(
                stamp_parent,
                parent_identity,
                parent_descriptor,
            )
            return resolved_stamp_path
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_name is not None and temporary_identity is not None:
                try:
                    current_identity = _identity_from_stat(
                        os.stat(
                            temporary_name,
                            dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                    )
                    if current_identity == temporary_identity:
                        os.unlink(temporary_name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    pass
            if owned_parent_descriptor:
                os.close(parent_descriptor)

    _assert_stamp_parent(stamp_parent, parent_identity, None)
    if os.path.lexists(resolved_stamp_path):
        _assert_plain_file(resolved_stamp_path, role="signature stamp")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved_stamp_path.parent,
            prefix=f".{resolved_stamp_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            temporary_identity = _identity_from_stat(os.fstat(handle.fileno()))
            if (
                not stat.S_ISREG(temporary_identity.file_type)
                or temporary_identity.link_count != 1
            ):
                raise RuntimeError(
                    "macOS backend temporary signature stamp is not a private file"
                )
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            if _identity_from_stat(os.fstat(handle.fileno())) != temporary_identity:
                raise RuntimeError(
                    "macOS backend temporary signature stamp identity changed"
                )
        _assert_plain_file(
            temporary_path,
            role="temporary signature stamp",
            expected_identity=temporary_identity,
        )
        replace_file(temporary_path, resolved_stamp_path)
        temporary_path = None
        _assert_plain_file(resolved_stamp_path, role="signature stamp")
        _assert_stamp_parent(stamp_parent, parent_identity, None)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return resolved_stamp_path


def _assert_stamp_parent(
    parent: Path,
    expected_identity: _PathIdentity,
    parent_descriptor: int | None,
) -> None:
    if parent_descriptor is not None and not _same_directory_identity(
        _identity_from_stat(os.fstat(parent_descriptor)),
        expected_identity,
    ):
        raise RuntimeError("macOS backend signature stamp parent identity changed")
    _assert_plain_directory(
        parent,
        role="signature stamp parent",
        expected_identity=expected_identity,
    )


def _stamp_entry_identity(
    stamp_path: Path,
    *,
    parent_identity: _PathIdentity,
    parent_descriptor: int | None,
    require_canonical_parent: bool = True,
) -> _PathIdentity | None:
    if require_canonical_parent:
        _assert_stamp_parent(stamp_path.parent, parent_identity, parent_descriptor)
    elif parent_descriptor is None:
        _assert_stamp_parent(stamp_path.parent, parent_identity, None)
    elif not _same_directory_identity(
        _identity_from_stat(os.fstat(parent_descriptor)),
        parent_identity,
    ):
        raise RuntimeError("macOS backend signature stamp parent identity changed")
    if parent_descriptor is None:
        if not os.path.lexists(stamp_path):
            return None
        return _assert_plain_file(stamp_path, role="signature stamp")
    try:
        identity = _identity_from_stat(
            os.stat(
                stamp_path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        )
    except FileNotFoundError:
        return None
    if _identity_is_link(identity):
        raise ValueError(
            "macOS backend signature stamp must not be a link or reparse point"
        )
    if not stat.S_ISREG(identity.file_type):
        raise ValueError("macOS backend signature stamp must be a regular file")
    if identity.link_count != 1:
        raise ValueError("macOS backend signature stamp must not be a hard link")
    if require_canonical_parent:
        _assert_stamp_parent(stamp_path.parent, parent_identity, parent_descriptor)
    return identity


def _unlink_codesign_stamp(
    stamp_path: Path,
    *,
    parent_identity: _PathIdentity,
    parent_descriptor: int | None,
    suppress_errors: bool = False,
) -> bool:
    try:
        identity = _stamp_entry_identity(
            stamp_path,
            parent_identity=parent_identity,
            parent_descriptor=parent_descriptor,
            require_canonical_parent=not suppress_errors,
        )
        if identity is None:
            return False
        if parent_descriptor is None:
            stamp_path.unlink()
        else:
            os.unlink(stamp_path.name, dir_fd=parent_descriptor)
        if not suppress_errors:
            _assert_stamp_parent(
                stamp_path.parent,
                parent_identity,
                parent_descriptor,
            )
        return True
    except (OSError, RuntimeError, ValueError):
        if suppress_errors:
            return False
        raise


def _load_codesign_state(
    stamp_path: Path,
    *,
    expected_identity: _PathIdentity | None = None,
    parent_identity: _PathIdentity | None = None,
    parent_descriptor: int | None = None,
) -> dict[str, object] | None:
    if parent_identity is None:
        parent_identity = _assert_plain_directory(
            stamp_path.parent,
            role="signature stamp parent",
        )
    try:
        identity = _stamp_entry_identity(
            stamp_path,
            parent_identity=parent_identity,
            parent_descriptor=parent_descriptor,
        )
        if identity is None:
            return None
        if expected_identity is not None and identity != expected_identity:
            raise RuntimeError("macOS backend signature stamp identity changed")
        if parent_descriptor is None:
            handle = stamp_path.open("r", encoding="utf-8")
        else:
            flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
            flags |= int(getattr(os, "O_NOFOLLOW", 0))
            descriptor = os.open(
                stamp_path.name,
                flags,
                dir_fd=parent_descriptor,
            )
            handle = os.fdopen(descriptor, "r", encoding="utf-8")
        with handle:
            if _identity_from_stat(os.fstat(handle.fileno())) != identity:
                raise RuntimeError(
                    "macOS backend signature stamp identity changed before reading"
                )
            text = handle.read(1024 * 1024 + 1)
            if len(text) > 1024 * 1024:
                return None
            if _identity_from_stat(os.fstat(handle.fileno())) != identity:
                raise RuntimeError(
                    "macOS backend signature stamp identity changed while reading"
                )
        current_identity = _stamp_entry_identity(
            stamp_path,
            parent_identity=parent_identity,
            parent_descriptor=parent_descriptor,
        )
        if current_identity != identity:
            raise RuntimeError("macOS backend signature stamp identity changed")
        payload = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _assert_stamp_unchanged(
    venv: Path,
    stamp_path: Path,
    *,
    expected_identity: _PathIdentity,
    expected_state: Mapping[str, object],
    parent_identity: _PathIdentity,
    parent_descriptor: int | None,
) -> None:
    current_identity = _stamp_entry_identity(
        stamp_path,
        parent_identity=parent_identity,
        parent_descriptor=parent_descriptor,
    )
    if current_identity != expected_identity:
        raise RuntimeError("macOS backend signature stamp identity changed")
    _assert_resolved_containment(venv, venv, role="runtime root")
    current_state = _load_codesign_state(
        stamp_path,
        expected_identity=expected_identity,
        parent_identity=parent_identity,
        parent_descriptor=parent_descriptor,
    )
    if current_state != dict(expected_state):
        raise RuntimeError("macOS backend signature stamp changed during verification")


def _run_codesign_command(
    command: list[str],
    *,
    action: str,
    run_command,
    path_prefixes: Mapping[str, object],
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
        raise RuntimeError(
            f"macOS backend native library {action} timed out"
        ) from exc
    if result.returncode == 0:
        return True
    detail = bounded_process_failure_detail(
        result,
        path_prefixes=path_prefixes,
    )
    suffix = f": {detail}" if detail else ""
    if action == "verify cached signature":
        return False
    raise RuntimeError(
        f"macOS backend native library {action} failed{suffix}"
    )


@contextmanager
def _directory_bound_command_path(
    path: Path,
    parent_identity: _PathIdentity,
    *,
    role: str,
):
    if os.name == "nt":
        yield str(path), None
        return

    parent_descriptor = _open_validated_directory(
        path.parent,
        parent_identity,
        role=role,
    )
    try:
        yield path.name, parent_descriptor
    finally:
        os.close(parent_descriptor)


def _verify_native_libraries(
    venv: Path,
    snapshot: _SigningSnapshot,
    *,
    action: str,
    run_command,
    path_prefixes: Mapping[str, object],
) -> bool:
    for library in snapshot.libraries:
        _assert_snapshot_roots(venv, snapshot)
        _assert_native_library(venv, library)
        with _directory_bound_command_path(
            library.path,
            library.parent_identity,
            role="native library parent",
        ) as (command_path, parent_descriptor):
            if not _run_codesign_command(
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    "--verbose=2",
                    command_path,
                ],
                action=action,
                run_command=run_command,
                path_prefixes=path_prefixes,
                working_directory_fd=parent_descriptor,
            ):
                return False
        _assert_snapshot_roots(venv, snapshot)
        _assert_native_library(venv, library)
    return True


def _validate_signing_paths(
    project_root: Path,
    venv: Path,
    state_path: Path,
    stamp_path: Path,
) -> None:
    expected_venv = project_root / BACKEND_RUNTIME_VENV_NAME
    if os.path.normcase(os.path.abspath(venv)) != os.path.normcase(
        os.path.abspath(expected_venv)
    ):
        raise ValueError(
            "macOS backend signer requires the dedicated runtime venv at "
            f"{expected_venv}"
        )
    if state_path != venv / BACKEND_ENVIRONMENT_STATE_NAME:
        raise ValueError(
            "macOS backend signer received an unexpected environment state path"
        )
    if stamp_path != venv / MACOS_BACKEND_CODESIGN_STAMP_NAME:
        raise ValueError(
            "macOS backend signer received an unexpected signature stamp path"
        )


def _sign_macos_backend_runtime_locked(
    *,
    venv: Path,
    state_path: Path,
    stamp_path: Path,
    run_command,
    replace_file: Callable[..., object],
    force: bool,
) -> MacOSBackendSigningOutcome:
    venv_descriptor: int | None = None
    venv_identity: _PathIdentity | None = None
    try:
        path_prefixes = {
            "<BACKEND_RUNTIME>": venv,
            "<PROJECT_ROOT>": venv.parent,
            "<USER_HOME>": Path.home(),
        }
        snapshot = _build_signing_snapshot(venv, state_path)
        venv_identity = snapshot.venv_identity
        if os.name != "nt":
            venv_descriptor = _open_validated_directory(
                venv,
                venv_identity,
                role="runtime root",
            )
        expected_state = _codesign_state_from_snapshot(venv, state_path, snapshot)
        libraries = snapshot.libraries
        stamp_identity: _PathIdentity | None = None
        stamp_identity = _stamp_entry_identity(
            stamp_path,
            parent_identity=venv_identity,
            parent_descriptor=venv_descriptor,
        )
        stored_state = _load_codesign_state(
            stamp_path,
            expected_identity=stamp_identity,
            parent_identity=venv_identity,
            parent_descriptor=venv_descriptor,
        )
        if not force and stored_state == expected_state:
            if stamp_identity is None:
                raise RuntimeError("macOS backend signature stamp identity is unavailable")
            if _verify_native_libraries(
                venv,
                snapshot,
                action="verify cached signature",
                run_command=run_command,
                path_prefixes=path_prefixes,
            ):
                _assert_stamp_unchanged(
                    venv,
                    stamp_path,
                    expected_identity=stamp_identity,
                    expected_state=expected_state,
                    parent_identity=venv_identity,
                    parent_descriptor=venv_descriptor,
                )
                verified_snapshot, verified_state = _stable_rescan(
                    venv,
                    state_path,
                    expected_snapshot=snapshot,
                    expected_state=expected_state,
                    phase="during cached signature verification",
                )
                _assert_stamp_unchanged(
                    venv,
                    stamp_path,
                    expected_identity=stamp_identity,
                    expected_state=verified_state,
                    parent_identity=venv_identity,
                    parent_descriptor=venv_descriptor,
                )
                return MacOSBackendSigningOutcome(
                    reused=True,
                    library_count=len(verified_snapshot.libraries),
                )

        _unlink_codesign_stamp(
            stamp_path,
            parent_identity=venv_identity,
            parent_descriptor=venv_descriptor,
        )
        staging_root: Path | None = None
        staging_root_identity: _PathIdentity | None = None
        try:
            snapshot = _build_signing_snapshot(venv, state_path)
            expected_state = _codesign_state_from_snapshot(
                venv,
                state_path,
                snapshot,
            )
            snapshot, expected_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=snapshot,
                expected_state=expected_state,
                phase="before staging native libraries",
            )
            libraries = snapshot.libraries
            staging_root, staging_root_identity = _create_private_staging_root(
                venv,
                snapshot,
                venv_descriptor=venv_descriptor,
            )
            expected_hashes = {
                str(entry["path"]): str(entry["sha256"])
                for entry in expected_state["native_libraries"]
            }
            staged_libraries = [
                _copy_native_library_to_staging(
                    venv,
                    snapshot,
                    library,
                    staging_root=staging_root,
                    staging_root_identity=staging_root_identity,
                    index=index,
                    expected_sha256=expected_hashes[
                        library.path.relative_to(venv).as_posix()
                    ],
                )
                for index, library in enumerate(libraries)
            ]
            snapshot, expected_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=snapshot,
                expected_state=expected_state,
                phase="while staging native libraries",
            )

            signed_staged_libraries: list[_StagedNativeLibrary] = []
            for staged in staged_libraries:
                _assert_snapshot_roots(venv, snapshot)
                _assert_native_library(venv, staged.source)
                _assert_staged_library(
                    venv,
                    staging_root,
                    staging_root_identity,
                    staged,
                )
                with _directory_bound_command_path(
                    staged.path,
                    staged.parent_identity,
                    role="codesign staging directory",
                ) as (command_path, staging_parent_descriptor):
                    try:
                        xattr_result = run_bounded_subprocess(
                            ["xattr", "-c", command_path],
                            run_command=run_command,
                            working_directory_fd=staging_parent_descriptor,
                            path_prefixes=path_prefixes,
                        )
                    except subprocess.TimeoutExpired as exc:
                        raise RuntimeError(
                            "macOS backend extended attribute cleanup timed out"
                        ) from exc
                    if xattr_result.returncode != 0:
                        detail = bounded_process_failure_detail(
                            xattr_result,
                            path_prefixes=path_prefixes,
                        )
                        suffix = f": {detail}" if detail else ""
                        raise RuntimeError(
                            "macOS backend extended attribute cleanup failed"
                            f"{suffix}"
                        )
                    _assert_staged_library(
                        venv,
                        staging_root,
                        staging_root_identity,
                        staged,
                    )
                    _assert_native_library(venv, staged.source)

                    _run_codesign_command(
                        [
                            "codesign",
                            "--force",
                            "--sign",
                            "-",
                            "--timestamp=none",
                            command_path,
                        ],
                        action="sign staged library",
                        run_command=run_command,
                        path_prefixes=path_prefixes,
                        working_directory_fd=staging_parent_descriptor,
                    )
                    _assert_snapshot_roots(venv, snapshot)
                    _assert_native_library(venv, staged.source)
                    signed_staged = _StagedNativeLibrary(
                        source=staged.source,
                        path=staged.path,
                        identity=_assert_plain_file(
                            staged.path,
                            role="staged native library",
                        ),
                        parent_identity=staged.parent_identity,
                    )
                    _assert_staged_library(
                        venv,
                        staging_root,
                        staging_root_identity,
                        signed_staged,
                    )
                    _run_codesign_command(
                        [
                            "codesign",
                            "--verify",
                            "--strict",
                            "--verbose=2",
                            command_path,
                        ],
                        action="verify staged library",
                        run_command=run_command,
                        path_prefixes=path_prefixes,
                        working_directory_fd=staging_parent_descriptor,
                    )
                _assert_staged_library(
                    venv,
                    staging_root,
                    staging_root_identity,
                    signed_staged,
                )
                _assert_native_library(venv, staged.source)
                signed_staged_libraries.append(signed_staged)

            snapshot, expected_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=snapshot,
                expected_state=expected_state,
                phase="while signing staged native libraries",
            )
            signed_libraries = [
                _replace_staged_native_library(
                    venv,
                    snapshot,
                    staged,
                    staging_root=staging_root,
                    staging_root_identity=staging_root_identity,
                )
                for staged in signed_staged_libraries
            ]

            signed_snapshot = _build_signing_snapshot(venv, state_path)
            expected_signed_snapshot = _SigningSnapshot(
                venv_identity=snapshot.venv_identity,
                library_root_identity=snapshot.library_root_identity,
                state_identity=snapshot.state_identity,
                libraries=tuple(signed_libraries),
            )
            _assert_equivalent_snapshot(
                expected_signed_snapshot,
                signed_snapshot,
                phase="while replacing signed native libraries",
            )
            signed_state = _codesign_state_from_snapshot(
                venv,
                state_path,
                signed_snapshot,
            )
            signed_snapshot, signed_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=signed_snapshot,
                expected_state=signed_state,
                phase="before signed signature verification",
            )
            _verify_native_libraries(
                venv,
                signed_snapshot,
                action="verify signed library",
                run_command=run_command,
                path_prefixes=path_prefixes,
            )
            verified_snapshot, verified_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=signed_snapshot,
                expected_state=signed_state,
                phase="during signed signature verification",
            )
            write_macos_backend_codesign_state(
                stamp_path,
                verified_state,
                replace_file=replace_file,
                parent_identity=venv_identity,
                parent_descriptor=venv_descriptor,
            )
            written_stamp_identity = _stamp_entry_identity(
                stamp_path,
                parent_identity=venv_identity,
                parent_descriptor=venv_descriptor,
            )
            if written_stamp_identity is None:
                raise RuntimeError("macOS backend signature stamp is unavailable")
            final_snapshot, final_state = _stable_rescan(
                venv,
                state_path,
                expected_snapshot=verified_snapshot,
                expected_state=verified_state,
                phase="while writing signature stamp",
            )
            _assert_stamp_unchanged(
                venv,
                stamp_path,
                expected_identity=written_stamp_identity,
                expected_state=final_state,
                parent_identity=venv_identity,
                parent_descriptor=venv_descriptor,
            )
            return MacOSBackendSigningOutcome(
                reused=False,
                library_count=len(final_snapshot.libraries),
            )
        finally:
            if staging_root is not None and staging_root_identity is not None:
                _cleanup_private_staging_root(
                    venv,
                    snapshot.venv_identity,
                    staging_root,
                    staging_root_identity,
                    venv_descriptor=venv_descriptor,
                )
    except BaseException:
        if venv_identity is not None:
            _unlink_codesign_stamp(
                stamp_path,
                parent_identity=venv_identity,
                parent_descriptor=venv_descriptor,
                suppress_errors=True,
            )
        raise
    finally:
        if venv_descriptor is not None:
            os.close(venv_descriptor)


def sign_macos_backend_runtime(
    *,
    project_root: str | Path,
    venv: str | Path,
    state_path: str | Path,
    stamp_path: str | Path,
    run_command=subprocess.run,
    replace_file: Callable[..., object] = os.replace,
    system_name: str | None = None,
    force: bool = False,
    lock_timeout_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
) -> MacOSBackendSigningOutcome:
    resolved_system_name = platform.system() if system_name is None else system_name
    if resolved_system_name != "Darwin":
        return MacOSBackendSigningOutcome(reused=False, library_count=0, skipped=True)

    resolved_project_root = Path(project_root).resolve()
    resolved_venv = Path(os.path.abspath(venv))
    resolved_state_path = Path(os.path.abspath(state_path))
    resolved_stamp_path = Path(os.path.abspath(stamp_path))
    _validate_signing_paths(
        resolved_project_root,
        resolved_venv,
        resolved_state_path,
        resolved_stamp_path,
    )

    with backend_runtime_lock(
        resolved_project_root,
        timeout_seconds=lock_timeout_seconds,
    ):
        return _sign_macos_backend_runtime_locked(
            venv=resolved_venv,
            state_path=resolved_state_path,
            stamp_path=resolved_stamp_path,
            run_command=run_command,
            replace_file=replace_file,
            force=force,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or ad-hoc sign macOS backend runtime native libraries.",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--venv", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--stamp", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        outcome = sign_macos_backend_runtime(
            project_root=args.project_root,
            venv=args.venv,
            state_path=args.state,
            stamp_path=args.stamp,
            force=args.force,
            lock_timeout_seconds=args.lock_timeout_seconds,
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"macOS backend runtime signing failed: {exc}", file=sys.stderr)
        return 1

    if outcome.skipped:
        print("macOS backend runtime signing skipped on this platform")
    elif outcome.reused:
        print(
            "macOS backend runtime signatures verified "
            f"({outcome.library_count} native libraries)"
        )
    else:
        print(
            "macOS backend runtime signatures refreshed "
            f"({outcome.library_count} native libraries)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
