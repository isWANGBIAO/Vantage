from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
    build_backend_environment_state,
    compute_requirements_sha256,
    current_platform_identity,
    current_python_identity,
    environment_state_validation_error,
    load_backend_environment_state,
    normalize_distribution_closure,
    write_backend_environment_state,
)


BACKEND_RUNTIME_VENV_NAME = ".venv-backend-runtime-gpu"
MACOS_CODESIGN_STAMP_NAME = ".macos-native-codesign.sha256"
PINNED_BOOTSTRAP_PIP = "pip==25.3"
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
    if candidate.exists():
        if candidate.is_symlink():
            raise ValueError("dedicated backend runtime venv must not be a symbolic link")
        if _normalized_path_text(candidate.resolve()) != _normalized_path_text(candidate):
            raise ValueError("dedicated backend runtime venv must be located inside project root")
        if not candidate.is_dir():
            raise ValueError("dedicated backend runtime venv path must be a directory")
    return candidate


def safe_remove_backend_runtime_venv(
    project_root: str | Path,
    venv: str | Path,
    *,
    remove_tree: Callable[[str | Path], object] = shutil.rmtree,
) -> None:
    safe_venv = validate_backend_runtime_venv_path(project_root, venv)
    if safe_venv.exists():
        remove_tree(safe_venv)


def _invalidate_environment_markers(venv: Path) -> None:
    for marker_name in (
        BACKEND_ENVIRONMENT_STATE_NAME,
        LEGACY_REQUIREMENTS_STAMP_NAME,
        MACOS_CODESIGN_STAMP_NAME,
    ):
        (venv / marker_name).unlink(missing_ok=True)


def _run_checked(command: list[str], run_command) -> None:
    result = run_command(command, check=False)
    if result.returncode == 0:
        return
    detail = str(getattr(result, "stderr", "") or getattr(result, "stdout", "")).strip()
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(
        f"command failed with exit code {result.returncode}: {' '.join(command)}{suffix}"
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
    result = run_command(
        [str(python_executable), "-c", _ENVIRONMENT_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout).strip()
        raise RuntimeError(f"backend environment metadata probe failed: {detail}")
    payload = _parse_last_json_line(result.stdout)
    payload["distributions"] = normalize_distribution_closure(
        payload.get("distributions", [])
    )
    return payload


def pip_check_succeeds(python_executable: Path, run_command=subprocess.run) -> bool:
    result = run_command(
        [str(python_executable), "-m", "pip", "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def required_imports_succeed(
    python_executable: Path,
    run_command=subprocess.run,
) -> bool:
    result = run_command(
        [str(python_executable), "-c", _REQUIRED_IMPORTS_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
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
    result = run_command(
        [str(python_executable), "-c", _OPENCV_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
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
        return BackendEnvironmentSyncOutcome(
            reused=True,
            reason="validated environment state and installed closure match",
            state=reusable_state,
        )

    _invalidate_environment_markers(safe_venv)
    safe_remove_backend_runtime_venv(
        resolved_root,
        safe_venv,
        remove_tree=remove_tree,
    )
    _run_checked(
        [resolved_creator_python, "-m", "venv", str(safe_venv)],
        run_command,
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
    )
    _run_checked(
        [str(target_python), "-m", "pip", "install", "-r", str(resolved_requirements)],
        run_command,
    )
    _run_checked(
        [
            str(target_python),
            str(resolved_normalizer),
            "--requirements-core",
            str(resolved_core),
        ],
        run_command,
    )

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
    return BackendEnvironmentSyncOutcome(
        reused=False,
        reason=reuse_error or "environment required a clean rebuild",
        state=state,
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
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Backend runtime environment synchronization failed: {exc}", file=sys.stderr)
        return 1
    action = "Reused" if outcome.reused else "Rebuilt"
    print(f"{action} validated backend runtime environment ({outcome.reason}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
