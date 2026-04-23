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
    load_backend_runtime_manifest,
    resolve_backend_runtime_layout,
    validate_backend_runtime_bundle,
)
from src.core.media_storage import save_media_paths_settings
from src.scripts.cleanup_vantage_python_processes import iter_vantage_server_processes, terminate_processes


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
    runtime_path_entries = [
        str(layout["resource_dir"]),
        str(layout["resource_dir"] / "torch" / "lib"),
        str(layout["resource_dir"] / "onnxruntime" / "capi"),
    ]
    existing_path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    env["PATH"] = os.pathsep.join(runtime_path_entries + existing_path_entries)
    env["VANTAGE_APP_MODE"] = "packaged"
    env["VANTAGE_DATA_DIR"] = str(smoke_data_dir)
    env["VANTAGE_CONFIG_DIR"] = str(config_dir)
    env.pop("VANTAGE_PROJECT_ROOT", None)
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
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    layout = resolve_backend_runtime_layout(PROJECT_ROOT)
    errors = validate_backend_runtime_bundle(
        layout,
        [],
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

    verify_dir = layout["build_root"] / "verification"
    verify_dir.mkdir(parents=True, exist_ok=True)
    smoke_log_path = verify_dir / "backend-runtime-smoke.log"

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

    _terminate_process_tree(process.pid)
    print(
        json.dumps(
            {
                "validated": True,
                "executable": str(executable_path),
                "smoke_log": str(smoke_log_path),
                "status": status_payload,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
