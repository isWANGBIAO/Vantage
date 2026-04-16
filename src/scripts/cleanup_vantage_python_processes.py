import argparse
import os
from pathlib import Path

import psutil


SERVER_SCRIPT_TOKENS = (
    "src/server.py",
    "src\\server.py",
    "src/scripts/run_server_background.py",
    "src\\scripts\\run_server_background.py",
)
INLINE_SERVER_TOKENS = ("from src.server import app", "uvicorn.run(app")
UVICORN_SERVER_TOKENS = ("src.server:app", "uvicorn")
DESKTOP_PROCESS_NAMES = ("electron", "electron.exe", "node", "node.exe", "npm", "npm.exe")
DESKTOP_ENTRYPOINT_TOKENS = (
    "src/webapp/main.cjs",
    "node_modules/electron/cli.js",
    "electron:start",
    "electron:dev",
)


def _normalize_text(value):
    return str(value or "").replace("\\", "/").lower()


def _safe_process_name(process):
    try:
        return process.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _safe_process_cmdline(process):
    try:
        return " ".join(process.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _safe_process_cwd(process):
    try:
        return process.cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _normalized_project_root(project_root):
    return _normalize_text(Path(project_root).resolve()).rstrip("/")


def _is_process_in_project(process, project_root):
    normalized_cmdline = _normalize_text(_safe_process_cmdline(process))
    normalized_cwd = _normalize_text(_safe_process_cwd(process)).rstrip("/")
    normalized_root = _normalized_project_root(project_root)

    return normalized_cwd.startswith(normalized_root) or normalized_root in normalized_cmdline


def _desktop_webapp_root(project_root):
    return _normalized_project_root(Path(project_root) / "src" / "webapp")


def _is_same_or_descendant_path(candidate, root):
    return candidate == root or candidate.startswith(f"{root}/")


def _belongs_to_current_project(normalized_cmdline, normalized_cwd, project_root):
    normalized_root = _normalized_project_root(project_root)
    normalized_webapp_root = _desktop_webapp_root(project_root)

    return (
        _is_same_or_descendant_path(normalized_cwd, normalized_webapp_root)
        or _is_same_or_descendant_path(normalized_cwd, normalized_root)
        or normalized_webapp_root in normalized_cmdline
        or normalized_root in normalized_cmdline
    )


def _is_vantage_desktop_entrypoint(normalized_cmdline, normalized_cwd, process_name, project_root):
    if not _belongs_to_current_project(normalized_cmdline, normalized_cwd, project_root):
        return False

    normalized_webapp_root = _desktop_webapp_root(project_root)

    if process_name in ("electron", "electron.exe") and _is_same_or_descendant_path(
        normalized_cwd, normalized_webapp_root
    ):
        return True

    if any(token in normalized_cmdline for token in ("electron:start", "electron:dev")) and _is_same_or_descendant_path(
        normalized_cwd, normalized_webapp_root
    ):
        return True

    if "--app-path=" in normalized_cmdline and normalized_webapp_root in normalized_cmdline:
        return True

    if "electron/cli.js" in normalized_cmdline and normalized_webapp_root in normalized_cmdline:
        return True

    if "main.cjs" in normalized_cmdline and normalized_webapp_root in normalized_cmdline:
        return True

    return False


def is_vantage_server_process(process, project_root):
    if process.pid == os.getpid():
        return False

    process_name = _normalize_text(_safe_process_name(process))
    if "python" not in process_name:
        return False

    normalized_cmdline = _normalize_text(_safe_process_cmdline(process))
    normalized_cwd = _normalize_text(_safe_process_cwd(process)).rstrip("/")
    normalized_root = _normalized_project_root(project_root)
    in_project_root = normalized_cwd == normalized_root
    belongs_to_project = _belongs_to_current_project(normalized_cmdline, normalized_cwd, project_root)

    has_server_script = any(token in normalized_cmdline for token in SERVER_SCRIPT_TOKENS)
    has_inline_server = all(token in normalized_cmdline for token in INLINE_SERVER_TOKENS)
    has_uvicorn_server = all(token in normalized_cmdline for token in UVICORN_SERVER_TOKENS)

    if has_server_script:
        return True

    if has_inline_server and in_project_root:
        return True

    if has_uvicorn_server and belongs_to_project:
        return True

    return False


def is_vantage_desktop_process(process, project_root):
    if process.pid == os.getpid():
        return False

    process_name = _normalize_text(_safe_process_name(process))
    if process_name not in DESKTOP_PROCESS_NAMES:
        return False

    normalized_cmdline = _normalize_text(_safe_process_cmdline(process))
    normalized_cwd = _normalize_text(_safe_process_cwd(process)).rstrip("/")
    return _is_vantage_desktop_entrypoint(normalized_cmdline, normalized_cwd, process_name, project_root)


def iter_vantage_server_processes(project_root):
    for process in psutil.process_iter(["pid", "name"]):
        if is_vantage_server_process(process, project_root):
            yield process


def iter_vantage_desktop_processes(project_root):
    for process in psutil.process_iter(["pid", "name"]):
        if is_vantage_desktop_process(process, project_root):
            yield process


def terminate_processes(processes):
    terminated = []
    for process in processes:
        try:
            cmdline = _safe_process_cmdline(process)
            process.kill()
            terminated.append((process.pid, cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return terminated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only print matched processes without terminating them")
    parser.add_argument(
        "--include-desktop",
        action="store_true",
        help="Also match project-local Electron/Node desktop processes",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    matched = list(iter_vantage_server_processes(project_root))
    if args.include_desktop:
        matched.extend(iter_vantage_desktop_processes(project_root))

    unique_matches = []
    seen_pids = set()
    for process in matched:
        if process.pid in seen_pids:
            continue
        seen_pids.add(process.pid)
        unique_matches.append(process)

    if not unique_matches:
        print("No residual Vantage Python backend processes found.")
        return 0

    if args.dry_run:
        for process in unique_matches:
            print(f"PID={process.pid} CMD={_safe_process_cmdline(process)}")
        return 0

    terminated = terminate_processes(unique_matches)
    for pid, cmdline in terminated:
        print(f"Killed PID={pid} CMD={cmdline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
