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


def test_prepare_server_runtime_log_creates_timestamped_log_and_latest_pointer(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    launched_at = datetime(2026, 4, 20, 22, 15, 30)

    log_path, latest_pointer = launcher._prepare_server_runtime_log(logs_dir, launched_at)

    assert log_path == logs_dir / "server" / "server-20260420_221530.log"
    assert log_path.parent.exists()
    assert latest_pointer == logs_dir / "server.latest.log"
    assert latest_pointer.read_text(encoding="utf-8") == str(log_path.resolve())


def test_prepare_server_runtime_log_does_not_require_fixed_server_log(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    launched_at = datetime(2026, 4, 20, 22, 16, 0)
    legacy_log = logs_dir / "server.log"
    logs_dir.mkdir()
    legacy_log.write_text("legacy session still locked elsewhere\n", encoding="utf-8")

    log_path, latest_pointer = launcher._prepare_server_runtime_log(logs_dir, launched_at)

    assert legacy_log.exists()
    assert log_path == logs_dir / "server" / "server-20260420_221600.log"
    assert latest_pointer.read_text(encoding="utf-8") == str(log_path.resolve())
