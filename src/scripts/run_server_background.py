import os
import runpy
import sys
from datetime import datetime
from pathlib import Path


def _redirect_standard_streams(log_path: Path):
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = open(2, "w", encoding="utf-8", buffering=1, closefd=False)
    return log_file


def _prepare_server_runtime_log(logs_dir: Path, launched_at: datetime):
    runtime_dir = logs_dir / "server"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / f"server-{launched_at.strftime('%Y%m%d_%H%M%S')}.log"
    latest_pointer = logs_dir / "server.latest.log"
    try:
        latest_pointer.write_text(str(log_path.resolve()), encoding="utf-8")
    except OSError:
        pass
    return log_path, latest_pointer


def main():
    launched_at = datetime.now()
    project_root = Path(__file__).resolve().parents[2]
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path, _ = _prepare_server_runtime_log(logs_dir, launched_at)

    banner = f"\n=== Background server launch {launched_at.isoformat()} ===\n"
    with open(log_path, "a", encoding="utf-8") as bootstrap_log:
        bootstrap_log.write(banner)

    os.chdir(project_root)
    _redirect_standard_streams(log_path)
    runpy.run_path(str(project_root / "src" / "server.py"), run_name="__main__")


if __name__ == "__main__":
    main()
