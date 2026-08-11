from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
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
    if expected_identity is not None and identity != expected_identity:
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
                    libraries.append(_NativeLibrary(path=path, identity=identity))
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
        actual.venv_identity != expected.venv_identity
        or actual.library_root_identity != expected.library_root_identity
        or actual.state_identity != expected.state_identity
    ):
        raise RuntimeError(f"macOS backend signing inputs changed {phase}")
    expected_paths = [library.path for library in expected.libraries]
    actual_paths = [library.path for library in actual.libraries]
    if actual_paths != expected_paths:
        raise RuntimeError(f"macOS backend native library closure changed {phase}")
    if any(
        actual_library.identity != expected_library.identity
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
    replace_file: Callable[[str | Path, str | Path], object] = os.replace,
) -> Path:
    resolved_stamp_path = Path(stamp_path)
    resolved_stamp_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(resolved_stamp_path):
        _assert_plain_file(resolved_stamp_path, role="signature stamp")
    payload = json.dumps(
        dict(state),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
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
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return resolved_stamp_path


def _load_codesign_state(
    stamp_path: Path,
    *,
    expected_identity: _PathIdentity | None = None,
) -> dict[str, object] | None:
    if not os.path.lexists(stamp_path):
        return None
    try:
        identity = _assert_plain_file(
            stamp_path,
            role="signature stamp",
            expected_identity=expected_identity,
        )
        with stamp_path.open("r", encoding="utf-8") as handle:
            if _identity_from_stat(os.fstat(handle.fileno())) != identity:
                raise RuntimeError(
                    "macOS backend signature stamp identity changed before reading"
                )
            text = handle.read()
            if _identity_from_stat(os.fstat(handle.fileno())) != identity:
                raise RuntimeError(
                    "macOS backend signature stamp identity changed while reading"
                )
        _assert_plain_file(
            stamp_path,
            role="signature stamp",
            expected_identity=identity,
        )
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
) -> None:
    _assert_plain_file(
        stamp_path,
        role="signature stamp",
        expected_identity=expected_identity,
    )
    _assert_resolved_containment(stamp_path, venv, role="signature stamp")
    current_state = _load_codesign_state(
        stamp_path,
        expected_identity=expected_identity,
    )
    if current_state != dict(expected_state):
        raise RuntimeError("macOS backend signature stamp changed during verification")


def _run_codesign_command(
    command: list[str],
    *,
    action: str,
    run_command,
    path_prefixes: Mapping[str, object],
) -> bool:
    try:
        result = run_bounded_subprocess(command, run_command=run_command)
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
        if not _run_codesign_command(
            [
                "codesign",
                "--verify",
                "--strict",
                "--verbose=2",
                str(library.path),
            ],
            action=action,
            run_command=run_command,
            path_prefixes=path_prefixes,
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
    replace_file: Callable[[str | Path, str | Path], object],
    force: bool,
) -> MacOSBackendSigningOutcome:
    try:
        path_prefixes = {
            "<BACKEND_RUNTIME>": venv,
            "<PROJECT_ROOT>": venv.parent,
            "<USER_HOME>": Path.home(),
        }
        snapshot = _build_signing_snapshot(venv, state_path)
        expected_state = _codesign_state_from_snapshot(venv, state_path, snapshot)
        libraries = snapshot.libraries
        stamp_identity: _PathIdentity | None = None
        if os.path.lexists(stamp_path):
            stamp_identity = _assert_plain_file(
                stamp_path,
                role="signature stamp",
            )
            _assert_resolved_containment(stamp_path, venv, role="signature stamp")
        stored_state = _load_codesign_state(
            stamp_path,
            expected_identity=stamp_identity,
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
                )
                return MacOSBackendSigningOutcome(
                    reused=True,
                    library_count=len(verified_snapshot.libraries),
                )

        stamp_path.unlink(missing_ok=True)
        snapshot = _build_signing_snapshot(venv, state_path)
        expected_state = _codesign_state_from_snapshot(venv, state_path, snapshot)
        snapshot, expected_state = _stable_rescan(
            venv,
            state_path,
            expected_snapshot=snapshot,
            expected_state=expected_state,
            phase="before extended attribute cleanup",
        )
        libraries = snapshot.libraries

        for library in libraries:
            _assert_snapshot_roots(venv, snapshot)
            _assert_native_library(venv, library)
            try:
                xattr_result = run_bounded_subprocess(
                    ["xattr", "-c", str(library.path)],
                    run_command=run_command,
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
                    f"macOS backend extended attribute cleanup failed{suffix}"
                )
            _assert_snapshot_roots(venv, snapshot)
            _assert_native_library(venv, library)
        snapshot, expected_state = _stable_rescan(
            venv,
            state_path,
            expected_snapshot=snapshot,
            expected_state=expected_state,
            phase="during extended attribute cleanup",
        )
        libraries = snapshot.libraries

        signed_libraries: list[_NativeLibrary] = []
        for library in libraries:
            _assert_snapshot_roots(venv, snapshot)
            _assert_native_library(venv, library)
            _run_codesign_command(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--timestamp=none",
                    str(library.path),
                ],
                action="sign",
                run_command=run_command,
                path_prefixes=path_prefixes,
            )
            _assert_snapshot_roots(venv, snapshot)
            signed_identity = _assert_plain_file(
                library.path,
                role="native library",
            )
            _assert_resolved_containment(
                library.path,
                venv / "lib",
                role="native library",
            )
            signed_libraries.append(
                _NativeLibrary(path=library.path, identity=signed_identity)
            )

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
            phase="while signing",
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
        )
        written_stamp_identity = _assert_plain_file(
            stamp_path,
            role="signature stamp",
        )
        _assert_resolved_containment(stamp_path, venv, role="signature stamp")
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
        )
        return MacOSBackendSigningOutcome(
            reused=False,
            library_count=len(final_snapshot.libraries),
        )
    except BaseException:
        stamp_path.unlink(missing_ok=True)
        raise


def sign_macos_backend_runtime(
    *,
    project_root: str | Path,
    venv: str | Path,
    state_path: str | Path,
    stamp_path: str | Path,
    run_command=subprocess.run,
    replace_file: Callable[[str | Path, str | Path], object] = os.replace,
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
