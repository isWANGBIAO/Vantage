import importlib.util
from datetime import datetime
from pathlib import Path


def _load_launcher_module():
    module_path = Path("src/scripts/run_server_background.py")
    spec = importlib.util.spec_from_file_location("run_server_background", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rotate_server_log_archives_previous_session(tmp_path):
    launcher = _load_launcher_module()
    log_path = tmp_path / "server.log"
    log_path.write_text("old session\n", encoding="utf-8")
    archive_dir = tmp_path / "archive"

    archive_path = launcher._rotate_server_log(
        log_path,
        launched_at=datetime(2026, 4, 5, 21, 30, 45),
        keep_count=5,
    )

    assert archive_path == archive_dir / "server_20260405_213045.log"
    assert archive_dir.exists()
    assert archive_path.read_text(encoding="utf-8") == "old session\n"
    assert not log_path.exists()


def test_rotate_server_log_skips_empty_current_log(tmp_path):
    launcher = _load_launcher_module()
    log_path = tmp_path / "server.log"
    log_path.touch()
    archive_dir = tmp_path / "archive"

    archive_path = launcher._rotate_server_log(
        log_path,
        launched_at=datetime(2026, 4, 5, 21, 31, 0),
        keep_count=5,
    )

    assert archive_path is None
    assert log_path.exists()
    assert list(archive_dir.glob("server_*.log")) == []


def test_rotate_server_log_prunes_old_archives(tmp_path):
    launcher = _load_launcher_module()
    log_path = tmp_path / "server.log"
    log_path.write_text("latest\n", encoding="utf-8")
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    existing_archives = [
        archive_dir / "server_20260405_210000.log",
        archive_dir / "server_20260405_210500.log",
        archive_dir / "server_20260405_211000.log",
    ]
    for path in existing_archives:
        path.write_text(path.name, encoding="utf-8")

    launcher._rotate_server_log(
        log_path,
        launched_at=datetime(2026, 4, 5, 21, 15, 0),
        keep_count=2,
    )

    remaining = sorted(path.name for path in archive_dir.glob("server_*.log"))
    assert remaining == [
        "server_20260405_211000.log",
        "server_20260405_211500.log",
    ]
