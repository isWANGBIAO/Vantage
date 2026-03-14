import argparse
import os
from pathlib import Path

import psutil


SERVER_SCRIPT_TOKENS = ("src/server.py", "src\\server.py")
INLINE_SERVER_TOKENS = ("from src.server import app", "uvicorn.run(app")


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


def is_vantage_server_process(process, project_root):
    if process.pid == os.getpid():
        return False

    process_name = _normalize_text(_safe_process_name(process))
    if "python" not in process_name:
        return False

    normalized_cmdline = _normalize_text(_safe_process_cmdline(process))
    normalized_cwd = _normalize_text(_safe_process_cwd(process))
    normalized_root = _normalize_text(Path(project_root).resolve())
    in_project_root = normalized_cwd == normalized_root

    has_server_script = any(token in normalized_cmdline for token in SERVER_SCRIPT_TOKENS)
    has_inline_server = all(token in normalized_cmdline for token in INLINE_SERVER_TOKENS)

    if has_server_script:
        return True

    if has_inline_server and in_project_root:
        return True

    return False


def iter_vantage_server_processes(project_root):
    for process in psutil.process_iter(["pid", "name"]):
        if is_vantage_server_process(process, project_root):
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
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    matched = list(iter_vantage_server_processes(project_root))

    if not matched:
        print("No residual Vantage Python backend processes found.")
        return 0

    if args.dry_run:
        for process in matched:
            print(f"PID={process.pid} CMD={_safe_process_cmdline(process)}")
        return 0

    terminated = terminate_processes(matched)
    for pid, cmdline in terminated:
        print(f"Killed PID={pid} CMD={cmdline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
