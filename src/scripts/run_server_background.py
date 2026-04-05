import os
import runpy
import sys
from datetime import datetime
from pathlib import Path

MAX_SERVER_LOG_ARCHIVES = 5


def _redirect_standard_streams(log_path: Path):
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = open(2, "w", encoding="utf-8", buffering=1, closefd=False)
    return log_file


def _rotate_server_log(log_path: Path, launched_at: datetime, keep_count: int = MAX_SERVER_LOG_ARCHIVES):
    if not log_path.exists() or log_path.stat().st_size == 0:
        return None

    archive_dir = log_path.parent / "archive"
    archive_dir.mkdir(exist_ok=True)

    archive_path = archive_dir / (
        f"{log_path.stem}_{launched_at.strftime('%Y%m%d_%H%M%S')}{log_path.suffix}"
    )
    suffix = 1
    while archive_path.exists():
        archive_path = archive_dir / (
            f"{log_path.stem}_{launched_at.strftime('%Y%m%d_%H%M%S')}_{suffix}{log_path.suffix}"
        )
        suffix += 1

    log_path.replace(archive_path)

    archived_logs = sorted(
        archive_dir.glob(f"{log_path.stem}_*{log_path.suffix}"),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale_log in archived_logs[keep_count:]:
        stale_log.unlink(missing_ok=True)

    return archive_path


def main():
    launched_at = datetime.now()
    project_root = Path(__file__).resolve().parents[2]
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / "server.log"
    _rotate_server_log(log_path, launched_at)

    banner = f"\n=== Background server launch {launched_at.isoformat()} ===\n"
    with open(log_path, "a", encoding="utf-8") as bootstrap_log:
        bootstrap_log.write(banner)

    os.chdir(project_root)
    _redirect_standard_streams(log_path)
    runpy.run_path(str(project_root / "src" / "server.py"), run_name="__main__")


if __name__ == "__main__":
    main()
