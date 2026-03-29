import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from src.manager.manager_main import Monitor
from src import server


def test_run_task_resets_sedentary_timer_after_stale_monitor_gap():
    with tempfile.TemporaryDirectory() as tmp_dir:
        monitor = Monitor(
            camera=None,
            paths={},
            photos_path=tmp_dir,
            screenshots_path=tmp_dir,
        )
        monitor.continuous_sit_start = 100.0
        monitor.last_monitor_heartbeat = 100.0

        with (
            patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
            patch("src.manager.manager_main.take_photo", return_value=(True, "photo.jpg")),
            patch("src.manager.manager_main.take_and_save_screenshots", return_value="screenshot.jpg"),
            patch("src.manager.manager_main.time.time", return_value=600.0),
        ):
            monitor.run_task()

        assert monitor.continuous_sit_start == 600.0


def test_get_sedentary_stats_treats_stale_monitor_as_not_sitting():
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=100.0,
            monitor_stale_timeout=2 * 60,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "is_sitting": False,
            "duration_minutes": 0,
            "threshold_minutes": 20,
        }
    finally:
        server.state.monitor = original_monitor
