from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
import warnings
from dataclasses import dataclass
from typing import Callable, Mapping


def _ensure_project_root_on_sys_path(script_path: str | Path | None = None) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.backend_environment_state import (
    BACKEND_ENVIRONMENT_STATE_NAME,
    LEGACY_REQUIREMENTS_STAMP_NAME,
    PINNED_BOOTSTRAP_PIP,
    build_backend_environment_state,
    compute_requirements_sha256,
    current_platform_identity,
    current_python_identity,
    environment_state_validation_error,
    load_backend_environment_state,
    normalize_distribution_closure,
    write_backend_environment_state,
)
from src.core.backend_runtime_lock import (
    DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    backend_runtime_lock,
    backend_runtime_lock_is_held,
)
from src.core.backend_runtime_packaging import (
    remove_conflicting_packaging_environment_libraries,
)
from src.utils.subprocess_safety import (
    bounded_process_failure_detail,
    run_bounded_subprocess,
)


BACKEND_RUNTIME_VENV_NAME = ".venv-backend-runtime-gpu"
OPENCV_DISTRIBUTIONS = (
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python",
    "opencv-python-headless",
)

_ENVIRONMENT_PROBE = r"""
import importlib.metadata as metadata
import json
import platform
import re
import sys

closure = {}
for distribution in metadata.distributions():
    raw_name = distribution.metadata.get("Name") or distribution.name
    name = re.sub(r"[-_.]+", "-", str(raw_name).strip()).lower()
    version = str(distribution.version).strip()
    previous = closure.get(name)
    if previous is not None and previous != version:
        raise RuntimeError(f"conflicting versions for {name}: {previous} and {version}")
    closure[name] = version

print(json.dumps({
    "python": {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": str(getattr(sys.implementation, "cache_tag", "")),
    },
    "platform": {
        "sys_platform": sys.platform,
        "system": platform.system(),
        "machine": platform.machine(),
    },
    "distributions": [f"{name}=={closure[name]}" for name in sorted(closure)],
}, sort_keys=True))
"""

_REQUIRED_IMPORTS_PROBE = r"""
import importlib
import sys

required = ["PyInstaller", "chinese_calendar", "cv2", "numpy", "zhdate"]
if sys.platform == "win32":
    required.append("lap")
for module_name in required:
    importlib.import_module(module_name)
"""

_OPENCV_PROBE = r"""
import cv2
import importlib.metadata as metadata
import json

names = (
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python",
    "opencv-python-headless",
)
installed = {}
for name in names:
    try:
        installed[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
print(json.dumps({"installed": installed, "cv2_version": cv2.__version__}, sort_keys=True))
"""


@dataclass(frozen=True)
class BackendEnvironmentSyncOutcome:
    reused: bool
    reason: str
    state: dict[str, object]


@dataclass(frozen=True)
class _PathIdentity:
    device: int
    inode: int
    file_type: int
    file_attributes: int


def _lstat_identity(path: Path) -> _PathIdentity:
    result = path.lstat()
    return _PathIdentity(
        device=int(result.st_dev),
        inode=int(result.st_ino),
        file_type=stat.S_IFMT(result.st_mode),
        file_attributes=int(getattr(result, "st_file_attributes", 0)),
    )


def _identity_is_symbolic_link(identity: _PathIdentity) -> bool:
    return stat.S_ISLNK(identity.file_type)


def _identity_is_windows_reparse(
    identity: _PathIdentity,
    *,
    platform_name: str | None = None,
) -> bool:
    resolved_platform = os.name if platform_name is None else platform_name
    if resolved_platform != "nt":
        return False
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(identity.file_attributes & reparse_flag)


def _identity_is_unsafe_root(
    identity: _PathIdentity,
    *,
    platform_name: str | None = None,
) -> bool:
    return _identity_is_symbolic_link(identity) or _identity_is_windows_reparse(
        identity,
        platform_name=platform_name,
    )


def backend_runtime_python_path(venv: str | Path) -> Path:
    resolved_venv = Path(venv)
    if os.name == "nt":
        return resolved_venv / "Scripts" / "python.exe"
    return resolved_venv / "bin" / "python"


def _normalized_path_text(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _path_is_lexically_within(path: Path, parent: Path) -> bool:
    try:
        common_path = os.path.commonpath(
            [
                os.path.abspath(os.fspath(path)),
                os.path.abspath(os.fspath(parent)),
            ]
        )
    except ValueError:
        return False
    return os.path.normcase(common_path) == _normalized_path_text(parent)


def validate_backend_runtime_venv_path(
    project_root: str | Path,
    venv: str | Path,
) -> Path:
    resolved_root = Path(project_root).resolve()
    candidate = Path(venv)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    candidate = Path(os.path.abspath(candidate))
    expected = resolved_root / BACKEND_RUNTIME_VENV_NAME
    if (
        _normalized_path_text(candidate) != _normalized_path_text(expected)
        or candidate.name != BACKEND_RUNTIME_VENV_NAME
        or _normalized_path_text(candidate.parent) != _normalized_path_text(resolved_root)
    ):
        raise ValueError(
            "refusing to mutate anything except the dedicated backend runtime venv "
            f"at {expected}"
        )
    return candidate


def _tree_contains_windows_reparse(
    path: Path,
    *,
    platform_name: str | None = None,
) -> bool:
    pending = [path]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                entry_stat = entry.stat(follow_symlinks=False)
                identity = _PathIdentity(
                    device=int(entry_stat.st_dev),
                    inode=int(entry_stat.st_ino),
                    file_type=stat.S_IFMT(entry_stat.st_mode),
                    file_attributes=int(
                        getattr(entry_stat, "st_file_attributes", 0)
                    ),
                )
                if _identity_is_windows_reparse(
                    identity,
                    platform_name=platform_name,
                ):
                    return True
                if stat.S_ISDIR(identity.file_type):
                    pending.append(Path(entry.path))
    return False


def _new_quarantine_path(venv: Path) -> Path:
    for _attempt in range(32):
        candidate = venv.with_name(f"{venv.name}.quarantine-{uuid.uuid4().hex}")
        if not os.path.lexists(candidate):
            return candidate
    raise RuntimeError("could not allocate a unique backend runtime quarantine path")


def _warn_retained_quarantine(quarantine: Path, reason: str) -> None:
    warnings.warn(
        f"Retained backend runtime quarantine {quarantine.name}: {reason}",
        RuntimeWarning,
        stacklevel=2,
    )


def safe_remove_backend_runtime_venv(
    project_root: str | Path,
    venv: str | Path,
    *,
    rename_path: Callable[[str | Path, str | Path], object] = os.rename,
    remove_tree: Callable[[str | Path], object] = shutil.rmtree,
    race_hook: Callable[[str, Path], object] | None = None,
    platform_name: str | None = None,
) -> None:
    resolved_root = Path(project_root).resolve()
    safe_venv = validate_backend_runtime_venv_path(resolved_root, venv)
    if not os.path.lexists(safe_venv):
        return
    if not backend_runtime_lock_is_held(resolved_root):
        raise RuntimeError(
            "backend runtime venv removal requires the backend runtime lifecycle lock"
        )

    initial_identity = _lstat_identity(safe_venv)
    if not (
        stat.S_ISDIR(initial_identity.file_type)
        or _identity_is_unsafe_root(
            initial_identity,
            platform_name=platform_name,
        )
    ):
        raise ValueError("dedicated backend runtime venv path must be a directory")
    if race_hook is not None:
        race_hook("after_initial_lstat", safe_venv)

    quarantine = _new_quarantine_path(safe_venv)
    try:
        rename_path(safe_venv, quarantine)
    except OSError as exc:
        raise RuntimeError(
            "could not atomically quarantine the existing backend runtime venv"
        ) from exc

    if (
        _normalized_path_text(quarantine.parent) != _normalized_path_text(resolved_root)
        or not quarantine.name.startswith(
            f"{BACKEND_RUNTIME_VENV_NAME}.quarantine-"
        )
    ):
        raise RuntimeError(
            f"backend runtime quarantine escaped the project root: {quarantine}"
        )

    renamed_identity = _lstat_identity(quarantine)
    if renamed_identity != initial_identity:
        raise RuntimeError(
            "backend runtime venv identity changed before quarantine rename; "
            f"retained {quarantine.name}"
        )
    if _identity_is_unsafe_root(
        renamed_identity,
        platform_name=platform_name,
    ):
        reason = (
            "root is a symbolic link"
            if _identity_is_symbolic_link(renamed_identity)
            else "root is a Windows reparse point"
        )
        _warn_retained_quarantine(quarantine, reason)
        return

    try:
        if _tree_contains_windows_reparse(
            quarantine,
            platform_name=platform_name,
        ):
            _warn_retained_quarantine(
                quarantine,
                "tree contains a Windows reparse point",
            )
            return
    except OSError as exc:
        _warn_retained_quarantine(
            quarantine,
            f"tree could not be safely inspected ({exc})",
        )
        return

    if race_hook is not None:
        race_hook("before_recursive_remove", quarantine)

    try:
        if _lstat_identity(quarantine) != renamed_identity:
            raise RuntimeError(
                "backend runtime quarantine identity changed before recursive cleanup"
            )
        if _tree_contains_windows_reparse(
            quarantine,
            platform_name=platform_name,
        ):
            _warn_retained_quarantine(
                quarantine,
                "tree gained a Windows reparse point before recursive cleanup",
            )
            return
        remove_tree(quarantine)
    except OSError as exc:
        raise RuntimeError(
            f"backend runtime quarantine cleanup failed; retained {quarantine.name}"
        ) from exc


def _runtime_subprocess_path_prefixes(
    project_root: Path,
    venv: Path,
) -> dict[str, Path]:
    return {
        "<BACKEND_RUNTIME>": venv,
        "<PROJECT_ROOT>": project_root,
        "<USER_HOME>": Path.home(),
    }


def _target_python_path_prefixes(python_executable: Path) -> dict[str, Path]:
    venv = python_executable.parent.parent
    return _runtime_subprocess_path_prefixes(venv.parent, venv)


def _run_checked(
    command: list[str],
    run_command,
    *,
    path_prefixes: Mapping[str, object],
) -> None:
    try:
        result = run_bounded_subprocess(command, run_command=run_command)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("backend environment command timed out") from exc
    if result.returncode == 0:
        return
    detail = bounded_process_failure_detail(
        result,
        path_prefixes=path_prefixes,
    )
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(
        f"backend environment command failed with exit code {result.returncode}{suffix}"
    )


def _parse_last_json_line(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            break
        return payload
    raise ValueError("child Python probe did not return a JSON object")


def probe_backend_environment(python_executable: Path, run_command=subprocess.run):
    try:
        result = run_bounded_subprocess(
            [str(python_executable), "-c", _ENVIRONMENT_PROBE],
            run_command=run_command,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("backend environment metadata probe timed out") from exc
    if result.returncode != 0:
        detail = bounded_process_failure_detail(
            result,
            path_prefixes=_target_python_path_prefixes(python_executable),
        )
        raise RuntimeError(f"backend environment metadata probe failed: {detail}")
    payload = _parse_last_json_line(result.stdout)
    payload["distributions"] = normalize_distribution_closure(
        payload.get("distributions", [])
    )
    return payload


def pip_check_succeeds(python_executable: Path, run_command=subprocess.run) -> bool:
    try:
        result = run_bounded_subprocess(
            [str(python_executable), "-m", "pip", "check"],
            run_command=run_command,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def required_imports_succeed(
    python_executable: Path,
    run_command=subprocess.run,
) -> bool:
    try:
        result = run_bounded_subprocess(
            [str(python_executable), "-c", _REQUIRED_IMPORTS_PROBE],
            run_command=run_command,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _read_opencv_contract(core_requirements: Path) -> tuple[str, str, str]:
    matches: list[tuple[str, str]] = []
    for raw_line in core_requirements.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*==\s*([^\s;]+)(?:\s*;.*)?", line)
        if not match:
            continue
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        if name in OPENCV_DISTRIBUTIONS:
            matches.append((name, match.group(2)))
    if len(matches) != 1 or matches[0][0] != "opencv-contrib-python":
        raise ValueError(
            "requirements core must contain exactly one opencv-contrib-python target"
        )
    name, wheel_version = matches[0]
    cv2_version = ".".join(wheel_version.split(".")[:3])
    if cv2_version.count(".") != 2:
        raise ValueError(f"invalid OpenCV wheel version: {wheel_version}")
    return name, wheel_version, cv2_version


def opencv_installation_matches(
    python_executable: Path,
    core_requirements: Path,
    run_command=subprocess.run,
) -> bool:
    try:
        target_name, target_wheel_version, target_cv2_version = _read_opencv_contract(
            core_requirements
        )
    except (OSError, ValueError):
        return False
    try:
        result = run_bounded_subprocess(
            [str(python_executable), "-c", _OPENCV_PROBE],
            run_command=run_command,
        )
    except subprocess.TimeoutExpired:
        return False
    if result.returncode != 0:
        return False
    try:
        payload = _parse_last_json_line(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return False
    return (
        payload.get("installed") == {target_name: target_wheel_version}
        and payload.get("cv2_version") == target_cv2_version
    )


def _reuse_validation_error(
    *,
    venv: Path,
    target_python: Path,
    requirements_sha256: str,
    creator_python_identity: Mapping[str, object],
    creator_platform_identity: Mapping[str, object],
    core_requirements: Path,
    force: bool,
    run_command,
    probe_environment,
    pip_check,
    import_check,
    opencv_check,
) -> tuple[str | None, dict[str, object] | None]:
    if force:
        return "forced synchronization requested", None
    if os.path.lexists(venv):
        try:
            venv_identity = _lstat_identity(venv)
        except OSError as exc:
            return f"target venv identity could not be inspected: {exc}", None
        if _identity_is_unsafe_root(venv_identity):
            return "target venv root is a symbolic link or Windows reparse point", None
    if not target_python.is_file():
        return "target Python is missing", None
    if (venv / LEGACY_REQUIREMENTS_STAMP_NAME).exists():
        return "legacy requirements stamp is present", None
    state = load_backend_environment_state(venv)
    if state is None:
        return "backend environment state is missing or invalid", None
    try:
        probe = probe_environment(target_python, run_command)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return f"backend environment metadata probe failed: {exc}", None
    if probe.get("python") != dict(creator_python_identity):
        return "target Python identity differs from the creating interpreter", None
    if probe.get("platform") != dict(creator_platform_identity):
        return "target platform identity differs from the creating interpreter", None
    error = environment_state_validation_error(
        state,
        requirements_sha256=requirements_sha256,
        python_identity=creator_python_identity,
        platform_identity=creator_platform_identity,
        distributions=probe.get("distributions", []),
    )
    if error:
        return error, None
    if not pip_check(target_python, run_command):
        return "pip check failed", None
    if not import_check(target_python, run_command):
        return "required backend imports failed", None
    if not opencv_check(target_python, core_requirements, run_command):
        return "OpenCV installation validation failed", None
    return None, state


def _synchronize_backend_runtime_environment_locked(
    *,
    project_root: str | Path,
    venv: str | Path,
    core_requirements: str | Path,
    requirements: str | Path,
    opencv_normalizer: str | Path,
    force: bool = False,
    creator_python: str | Path | None = None,
    creator_prefix: str | Path | None = None,
    creator_python_identity: Mapping[str, object] | None = None,
    creator_platform_identity: Mapping[str, object] | None = None,
    run_command=subprocess.run,
    remove_tree: Callable[[str | Path], object] = shutil.rmtree,
    probe_environment=probe_backend_environment,
    pip_check=pip_check_succeeds,
    import_check=required_imports_succeed,
    opencv_check=opencv_installation_matches,
) -> BackendEnvironmentSyncOutcome:
    resolved_root = Path(project_root).resolve()
    safe_venv = validate_backend_runtime_venv_path(resolved_root, venv)
    resolved_core = Path(core_requirements).resolve()
    resolved_requirements = Path(requirements).resolve()
    resolved_normalizer = Path(opencv_normalizer).resolve()
    expected_files = (resolved_core, resolved_requirements, resolved_normalizer)
    missing = [str(path) for path in expected_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing backend environment input: " + ", ".join(missing))

    raw_creator_python_path = Path(
        os.path.abspath(os.fspath(creator_python or sys.executable))
    )
    resolved_creator_python_path = raw_creator_python_path.resolve()
    raw_creator_prefix = Path(os.path.abspath(os.fspath(creator_prefix or sys.prefix)))
    resolved_creator_prefix = raw_creator_prefix.resolve()
    if (
        _path_is_lexically_within(raw_creator_python_path, safe_venv)
        or _path_is_within(resolved_creator_python_path, safe_venv)
        or _path_is_lexically_within(raw_creator_prefix, safe_venv)
        or _path_is_within(resolved_creator_prefix, safe_venv)
    ):
        raise ValueError(
            "backend environment synchronization must run from a Python "
            "outside the target backend runtime venv"
        )
    resolved_creator_python = str(resolved_creator_python_path)
    expected_python_identity = dict(
        creator_python_identity or current_python_identity()
    )
    expected_platform_identity = dict(
        creator_platform_identity or current_platform_identity()
    )
    requirements_sha256 = compute_requirements_sha256(
        resolved_core,
        resolved_requirements,
    )
    target_python = backend_runtime_python_path(safe_venv)
    subprocess_path_prefixes = _runtime_subprocess_path_prefixes(
        resolved_root,
        safe_venv,
    )
    reuse_error, reusable_state = _reuse_validation_error(
        venv=safe_venv,
        target_python=target_python,
        requirements_sha256=requirements_sha256,
        creator_python_identity=expected_python_identity,
        creator_platform_identity=expected_platform_identity,
        core_requirements=resolved_core,
        force=force,
        run_command=run_command,
        probe_environment=probe_environment,
        pip_check=pip_check,
        import_check=import_check,
        opencv_check=opencv_check,
    )
    if reuse_error is None and reusable_state is not None:
        try:
            removed_packaging_dlls = (
                remove_conflicting_packaging_environment_libraries(resolved_root)
            )
        except BaseException:
            (safe_venv / BACKEND_ENVIRONMENT_STATE_NAME).unlink(missing_ok=True)
            raise
        if removed_packaging_dlls:
            reuse_error, reusable_state = _reuse_validation_error(
                venv=safe_venv,
                target_python=target_python,
                requirements_sha256=requirements_sha256,
                creator_python_identity=expected_python_identity,
                creator_platform_identity=expected_platform_identity,
                core_requirements=resolved_core,
                force=False,
                run_command=run_command,
                probe_environment=probe_environment,
                pip_check=pip_check,
                import_check=import_check,
                opencv_check=opencv_check,
            )
    if reuse_error is None and reusable_state is not None:
        return BackendEnvironmentSyncOutcome(
            reused=True,
            reason="validated environment state and installed closure match",
            state=reusable_state,
        )

    safe_remove_backend_runtime_venv(
        resolved_root,
        safe_venv,
        remove_tree=remove_tree,
    )
    try:
        _run_checked(
            [resolved_creator_python, "-m", "venv", str(safe_venv)],
            run_command,
            path_prefixes=subprocess_path_prefixes,
        )
        target_python = backend_runtime_python_path(safe_venv)
        _run_checked(
            [
                str(target_python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                PINNED_BOOTSTRAP_PIP,
            ],
            run_command,
            path_prefixes=subprocess_path_prefixes,
        )
        _run_checked(
            [
                str(target_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(resolved_requirements),
            ],
            run_command,
            path_prefixes=subprocess_path_prefixes,
        )
        _run_checked(
            [
                str(target_python),
                str(resolved_normalizer),
                "--requirements-core",
                str(resolved_core),
            ],
            run_command,
            path_prefixes=subprocess_path_prefixes,
        )

        remove_conflicting_packaging_environment_libraries(resolved_root)
        probe = probe_environment(target_python, run_command)
        if probe.get("python") != expected_python_identity:
            raise RuntimeError("rebuilt target Python identity does not match creator")
        if probe.get("platform") != expected_platform_identity:
            raise RuntimeError("rebuilt target platform identity does not match creator")
        if not pip_check(target_python, run_command):
            raise RuntimeError("rebuilt backend environment failed pip check")
        if not import_check(target_python, run_command):
            raise RuntimeError("rebuilt backend environment failed required imports")
        if not opencv_check(target_python, resolved_core, run_command):
            raise RuntimeError("rebuilt backend environment failed OpenCV validation")

        state = build_backend_environment_state(
            resolved_core,
            resolved_requirements,
            python_identity=expected_python_identity,
            platform_identity=expected_platform_identity,
            distributions=probe.get("distributions", []),
        )
        write_backend_environment_state(safe_venv, state)
    except BaseException:
        (safe_venv / BACKEND_ENVIRONMENT_STATE_NAME).unlink(missing_ok=True)
        raise
    return BackendEnvironmentSyncOutcome(
        reused=False,
        reason=reuse_error or "environment required a clean rebuild",
        state=state,
    )


def synchronize_backend_runtime_environment(
    *,
    project_root: str | Path,
    venv: str | Path,
    core_requirements: str | Path,
    requirements: str | Path,
    opencv_normalizer: str | Path,
    force: bool = False,
    creator_python: str | Path | None = None,
    creator_prefix: str | Path | None = None,
    creator_python_identity: Mapping[str, object] | None = None,
    creator_platform_identity: Mapping[str, object] | None = None,
    lock_timeout_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    run_command=subprocess.run,
    remove_tree: Callable[[str | Path], object] = shutil.rmtree,
    probe_environment=probe_backend_environment,
    pip_check=pip_check_succeeds,
    import_check=required_imports_succeed,
    opencv_check=opencv_installation_matches,
) -> BackendEnvironmentSyncOutcome:
    resolved_root = Path(project_root).resolve()
    with backend_runtime_lock(
        resolved_root,
        timeout_seconds=lock_timeout_seconds,
    ):
        return _synchronize_backend_runtime_environment_locked(
            project_root=resolved_root,
            venv=venv,
            core_requirements=core_requirements,
            requirements=requirements,
            opencv_normalizer=opencv_normalizer,
            force=force,
            creator_python=creator_python,
            creator_prefix=creator_prefix,
            creator_python_identity=creator_python_identity,
            creator_platform_identity=creator_platform_identity,
            run_command=run_command,
            remove_tree=remove_tree,
            probe_environment=probe_environment,
            pip_check=pip_check,
            import_check=import_check,
            opencv_check=opencv_check,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize Vantage's dedicated backend packaging environment.",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--venv", required=True, type=Path)
    parser.add_argument("--core-requirements", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--opencv-normalizer", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    )
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        outcome = synchronize_backend_runtime_environment(
            project_root=args.project_root,
            venv=args.venv,
            core_requirements=args.core_requirements,
            requirements=args.requirements,
            opencv_normalizer=args.opencv_normalizer,
            force=args.force,
            lock_timeout_seconds=args.lock_timeout_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Backend runtime environment synchronization failed: {exc}", file=sys.stderr)
        return 1
    action = "Reused" if outcome.reused else "Rebuilt"
    print(f"{action} validated backend runtime environment ({outcome.reason}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
