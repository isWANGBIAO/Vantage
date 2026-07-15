from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil


def _ensure_project_root_on_sys_path(
    script_path: str | Path | None = None,
    path_list: list[str] | None = None,
) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    resolved_path_list = path_list if path_list is not None else sys.path
    project_root_str = str(project_root)
    if project_root_str not in resolved_path_list:
        resolved_path_list.insert(0, project_root_str)
    return project_root


PROJECT_ROOT = _ensure_project_root_on_sys_path()

from src.core.backend_runtime_packaging import (
    collect_backend_runtime_resources,
    get_backend_runtime_executable_name,
    load_backend_runtime_manifest,
    resolve_backend_runtime_layout,
    validate_backend_runtime_bundle,
)
from src.core.runtime_library_bootstrap import collect_runtime_library_dirs
from src.core.media_storage import save_media_paths_settings
from src.scripts.cleanup_vantage_python_processes import iter_vantage_server_processes, terminate_processes


BLOCKING_RUNTIME_PATTERNS = (
    "c10.dll",
    "DLL load failed",
    "Live face analysis error",
    "Missing packaged runtime module",
    "No module named",
    "Missing face detection model",
    "Missing detection model",
    "Failed to warm camera face detector",
)
REQUIRED_RUNTIME_LOG_MARKERS = (
    "Camera face detector warmed up successfully.",
)
RUNTIME_LAUNCH_BANNER_PREFIX = "=== Background server launch "


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the packaged backend runtime and optionally smoke-test it.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="Maximum number of seconds to wait for /api/status during smoke launch.",
    )
    parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="Only validate the built files and manifest without starting the executable.",
    )
    return parser


def _seed_smoke_media_paths(smoke_data_dir: Path) -> Path:
    config_dir = smoke_data_dir / "config"
    photos_dir = smoke_data_dir / "photos"
    screenshots_dir = smoke_data_dir / "screenshots"
    photos_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    save_media_paths_settings(
        photos_dir,
        screenshots_dir,
        settings_file=config_dir / "media-paths.json",
    )
    return config_dir


def _build_smoke_environment(layout: dict[str, Path]) -> dict[str, str]:
    smoke_data_dir = layout["build_root"] / "smoke-data"
    config_dir = _seed_smoke_media_paths(smoke_data_dir)
    env = os.environ.copy()
    runtime_path_entries = [str(path) for path in collect_runtime_library_dirs(layout["runtime_dir"])]
    existing_path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    env["PATH"] = os.pathsep.join(runtime_path_entries + existing_path_entries)
    env["VANTAGE_APP_MODE"] = "packaged"
    env["VANTAGE_DATA_DIR"] = str(smoke_data_dir)
    env["VANTAGE_CONFIG_DIR"] = str(config_dir)
    env["VANTAGE_MACOS_SKIP_CAMERA_AUTH"] = "1"
    env["OPENCV_AVFOUNDATION_SKIP_AUTH"] = "1"
    env["VANTAGE_PREWARM_FACE_DETECTION_ON_STARTUP"] = "1"
    env.pop("VANTAGE_PROJECT_ROOT", None)
    env.pop("VANTAGE_FACE_DETECTION_MODEL_PATH", None)
    return env


def _terminate_process_tree(pid: int):
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    children = process.children(recursive=True)
    for child in reversed(children):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            child.kill()
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        process.kill()


def _wait_for_status(timeout_seconds: int) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)

    raise RuntimeError(f"Timed out waiting for packaged backend status: {last_error}")


def _tail_text_file(path: Path, max_lines: int = 40) -> str:
    try:
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _status_matches_runtime_layout(status_payload: dict[str, object], layout: dict[str, Path]) -> bool:
    runtime = status_payload.get("runtime")
    if not isinstance(runtime, dict):
        return False
    cwd_name = runtime.get("cwd_name")
    return isinstance(cwd_name, str) and cwd_name == layout["resource_dir"].name


def _find_runtime_blockers(log_text: str) -> list[str]:
    return [pattern for pattern in BLOCKING_RUNTIME_PATTERNS if pattern in log_text]


def _resolve_runtime_server_log(smoke_data_dir: Path) -> Path | None:
    pointer_path = smoke_data_dir / "logs" / "server.latest.log"
    if not pointer_path.exists():
        return None

    try:
        target_text = pointer_path.read_text(encoding="utf-8").strip()
        if not target_text:
            return None
        target = Path(target_text).resolve(strict=True)
        server_logs_root = (smoke_data_dir / "logs" / "server").resolve()
        target.relative_to(server_logs_root)
    except OSError:
        return None
    except ValueError:
        return None

    return target if target.is_file() else None


def _clear_runtime_server_log_pointer(smoke_data_dir: Path) -> None:
    pointer_path = smoke_data_dir / "logs" / "server.latest.log"
    try:
        pointer_path.unlink()
    except FileNotFoundError:
        pass


def _read_verified_runtime_server_log(
    smoke_data_dir: Path,
) -> tuple[Path | None, str, list[str]]:
    runtime_log_path = _resolve_runtime_server_log(smoke_data_dir)
    if runtime_log_path is None:
        return None, "", ["Packaged backend runtime log is missing or invalid."]

    try:
        runtime_log_text = runtime_log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return runtime_log_path, "", [
            f"Packaged backend runtime log is unreadable: {exc}"
        ]

    validation_errors = []
    launch_banner_index = runtime_log_text.rfind(RUNTIME_LAUNCH_BANNER_PREFIX)
    if launch_banner_index >= 0:
        current_launch_text = runtime_log_text[launch_banner_index:]
    else:
        current_launch_text = runtime_log_text
        validation_errors.append(
            "Packaged backend runtime log is missing the current launch banner."
        )

    if not current_launch_text.strip():
        validation_errors.append("Packaged backend runtime log is empty.")
    for marker in REQUIRED_RUNTIME_LOG_MARKERS:
        if marker not in current_launch_text:
            validation_errors.append(
                f"Packaged backend runtime log is missing success marker: {marker}"
            )

    return runtime_log_path, current_launch_text, validation_errors


def _iter_packaged_backend_processes(executable_name: str | None = None):
    resolved_executable_name = executable_name or get_backend_runtime_executable_name()
    for process in psutil.process_iter(["pid", "name", "exe"]):
        name = process.info.get("name")
        exe_path = process.info.get("exe")
        if name == resolved_executable_name:
            yield process
            continue
        if exe_path and Path(exe_path).name == resolved_executable_name:
            yield process


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    layout = resolve_backend_runtime_layout(PROJECT_ROOT)
    resources = collect_backend_runtime_resources(PROJECT_ROOT)
    errors = validate_backend_runtime_bundle(
        layout,
        resources,
    )
    if errors:
        for error in errors:
            print(error)
        return 1

    manifest = load_backend_runtime_manifest(layout)
    resource_outputs = manifest.get("resource_outputs", [])
    for relative_output in resource_outputs:
        packaged_path = layout["resource_dir"] / relative_output
        if not packaged_path.exists():
            errors.append(f"Missing runtime resource from manifest: {packaged_path}")

    if errors:
        for error in errors:
            print(error)
        return 1

    if args.skip_launch:
        print(json.dumps({"manifest": manifest, "validated": True}, indent=2, ensure_ascii=True))
        return 0

    existing_server_processes = list(iter_vantage_server_processes(PROJECT_ROOT))
    terminate_processes(existing_server_processes)
    terminate_processes(list(_iter_packaged_backend_processes()))

    verify_dir = layout["build_root"] / "verification"
    verify_dir.mkdir(parents=True, exist_ok=True)
    smoke_log_path = verify_dir / "backend-runtime-smoke.log"
    smoke_data_dir = layout["build_root"] / "smoke-data"

    try:
        _clear_runtime_server_log_pointer(smoke_data_dir)
    except OSError as exc:
        print(f"Could not clear previous packaged backend runtime log pointer: {exc}")
        return 1

    env = _build_smoke_environment(layout)
    executable_path = layout["executable_path"]

    with open(smoke_log_path, "w", encoding="utf-8") as smoke_log:
        process = subprocess.Popen(
            [str(executable_path)],
            cwd=str(layout["runtime_dir"]),
            env=env,
            stdout=smoke_log,
            stderr=smoke_log,
        )

    try:
        status_payload = _wait_for_status(args.timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        _terminate_process_tree(process.pid)
        log_tail = _tail_text_file(smoke_log_path)
        print(str(exc))
        if log_tail:
            print("--- smoke log tail ---")
            print(log_tail)
        return 1

    (
        runtime_log_path,
        runtime_log_text,
        runtime_log_validation_errors,
    ) = _read_verified_runtime_server_log(
        smoke_data_dir
    )
    runtime_blockers = _find_runtime_blockers(runtime_log_text)
    status_matches_runtime = _status_matches_runtime_layout(status_payload, layout)

    _terminate_process_tree(process.pid)
    if not status_matches_runtime:
        print(
            "Packaged backend status returned an unexpected runtime marker: "
            f"{status_payload.get('runtime')} (expected cwd_name={layout['resource_dir'].name})"
        )
        if runtime_log_path:
            print("--- runtime log tail ---")
            print(_tail_text_file(runtime_log_path))
        return 1

    if runtime_blockers:
        print("Packaged backend runtime log contains blocking errors: " + ", ".join(runtime_blockers))
        if runtime_log_path:
            print("--- runtime log tail ---")
            print(_tail_text_file(runtime_log_path))
        return 1

    if runtime_log_validation_errors:
        print(
            "Packaged backend runtime log validation failed: "
            + "; ".join(runtime_log_validation_errors)
        )
        if runtime_log_path:
            print("--- runtime log tail ---")
            print(_tail_text_file(runtime_log_path))
        return 1

    print(
        json.dumps(
            {
                "validated": True,
                "executable": str(executable_path),
                "smoke_log": str(smoke_log_path),
                "runtime_log": str(runtime_log_path) if runtime_log_path else None,
                "status": status_payload,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
