from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
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


BACKEND_RUNTIME_VENV_NAME = ".venv-backend-runtime-gpu"
MACOS_BACKEND_CODESIGN_STAMP_NAME = ".macos-native-codesign.sha256"
MACOS_BACKEND_CODESIGN_STATE_SCHEMA_VERSION = 1
NATIVE_LIBRARY_SUFFIXES = (".dylib", ".so")


@dataclass(frozen=True)
class MacOSBackendSigningOutcome:
    reused: bool
    library_count: int
    skipped: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_library_paths(venv: Path) -> list[Path]:
    library_root = venv / "lib"
    if not library_root.is_dir():
        raise FileNotFoundError(
            f"backend runtime library directory is missing: {library_root}"
        )
    paths = [
        path
        for path in library_root.rglob("*")
        if path.is_file() and path.suffix.lower() in NATIVE_LIBRARY_SUFFIXES
    ]
    return sorted(paths, key=lambda path: path.relative_to(venv).as_posix())


def build_macos_backend_codesign_state(
    venv: str | Path,
    state_path: str | Path,
) -> dict[str, object]:
    resolved_venv = Path(venv)
    resolved_state_path = Path(state_path)
    if not resolved_state_path.is_file():
        raise FileNotFoundError(
            f"backend runtime environment state is missing: {resolved_state_path}"
        )

    libraries = []
    for library in _native_library_paths(resolved_venv):
        library_stat = library.stat()
        libraries.append(
            {
                "path": library.relative_to(resolved_venv).as_posix(),
                "size": int(library_stat.st_size),
                "sha256": _sha256_file(library),
            }
        )
    return {
        "schema_version": MACOS_BACKEND_CODESIGN_STATE_SCHEMA_VERSION,
        "backend_environment_state_sha256": _sha256_file(resolved_state_path),
        "native_libraries": libraries,
    }


def write_macos_backend_codesign_state(
    stamp_path: str | Path,
    state: Mapping[str, object],
    *,
    replace_file: Callable[[str | Path, str | Path], object] = os.replace,
) -> Path:
    resolved_stamp_path = Path(stamp_path)
    resolved_stamp_path.parent.mkdir(parents=True, exist_ok=True)
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
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary_path, resolved_stamp_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return resolved_stamp_path


def _load_codesign_state(stamp_path: Path) -> dict[str, object] | None:
    if not stamp_path.is_file():
        return None
    try:
        payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _run_codesign_command(
    command: list[str],
    *,
    action: str,
    run_command,
) -> bool:
    result = run_command(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    detail = str(
        getattr(result, "stderr", "") or getattr(result, "stdout", "")
    ).strip()
    suffix = f": {detail}" if detail else ""
    if action == "verify cached signature":
        return False
    raise RuntimeError(
        f"macOS backend native library {action} failed for {command[-1]}{suffix}"
    )


def _verify_native_libraries(
    libraries: list[Path],
    *,
    action: str,
    run_command,
) -> bool:
    for library in libraries:
        if not _run_codesign_command(
            [
                "codesign",
                "--verify",
                "--strict",
                "--verbose=2",
                str(library),
            ],
            action=action,
            run_command=run_command,
        ):
            return False
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
        expected_state = build_macos_backend_codesign_state(venv, state_path)
        libraries = _native_library_paths(venv)
        stored_state = _load_codesign_state(stamp_path)
        if not force and stored_state == expected_state:
            if _verify_native_libraries(
                libraries,
                action="verify cached signature",
                run_command=run_command,
            ):
                return MacOSBackendSigningOutcome(
                    reused=True,
                    library_count=len(libraries),
                )

        stamp_path.unlink(missing_ok=True)
        run_command(
            ["xattr", "-cr", str(venv / "lib")],
            check=False,
            capture_output=True,
            text=True,
        )
        for library in libraries:
            _run_codesign_command(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--timestamp=none",
                    str(library),
                ],
                action="sign",
                run_command=run_command,
            )
        _verify_native_libraries(
            libraries,
            action="verify signed library",
            run_command=run_command,
        )
        signed_state = build_macos_backend_codesign_state(venv, state_path)
        write_macos_backend_codesign_state(
            stamp_path,
            signed_state,
            replace_file=replace_file,
        )
        return MacOSBackendSigningOutcome(
            reused=False,
            library_count=len(libraries),
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
