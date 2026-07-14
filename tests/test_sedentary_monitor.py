import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.manager.manager_main import Monitor
from src import server


def _make_monitor(tmp_path, *, state_path=None):
    return Monitor(
        camera=None,
        paths={},
        photos_path=str(tmp_path),
        screenshots_path=str(tmp_path),
        state_path=state_path,
    )


def test_presence_observations_preserve_start_across_unknown():
    with tempfile.TemporaryDirectory() as tmp_dir:
        monitor = _make_monitor(tmp_dir)

        monitor.record_presence_observation(True, observed_at=100.0)
        assert monitor.continuous_sit_start == 100.0
        assert monitor.last_observation_status == "PRESENT"
        assert monitor.last_observation_time == 100.0

        monitor.record_presence_observation(None, observed_at=150.0)
        assert monitor.continuous_sit_start == 100.0
        assert monitor.last_missing_time is None
        assert monitor.last_observation_status == "UNKNOWN"
        assert monitor.last_observation_time == 150.0

        monitor.record_presence_observation(True, observed_at=200.0)
        assert monitor.continuous_sit_start == 100.0
        assert monitor.last_missing_time is None
        assert monitor.last_observation_status == "PRESENT"
        assert monitor.last_observation_time == 200.0


def test_confirmed_absence_only_resets_after_full_grace_period(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    monitor = _make_monitor(tmp_path, state_path=state_path)

    monitor.record_presence_observation(True, observed_at=100.0)
    monitor.record_presence_observation(False, observed_at=110.0)
    monitor.record_presence_observation(False, observed_at=229.999)

    assert monitor.continuous_sit_start == 100.0
    assert monitor.last_missing_time == 110.0
    assert state_path.exists()

    monitor.record_presence_observation(False, observed_at=230.0)

    assert monitor.continuous_sit_start is None
    assert monitor.last_missing_time is None
    assert monitor.last_observation_status == "ABSENT"
    assert monitor.last_observation_time == 230.0
    assert not state_path.exists()


def test_unknown_observation_does_not_advance_existing_absence_debounce(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.record_presence_observation(True, observed_at=100.0)
    monitor.record_presence_observation(False, observed_at=110.0)

    monitor.record_presence_observation(None, observed_at=500.0)
    monitor.record_presence_observation(False, observed_at=501.0)

    assert monitor.continuous_sit_start == 100.0
    assert monitor.last_missing_time == 501.0


def test_run_task_records_unknown_photo_result_without_starting_absence_debounce(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.continuous_sit_start = 100.0

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(None, None)),
        patch("src.manager.manager_main.time.time", return_value=200.0),
    ):
        monitor.run_task()

    assert monitor.continuous_sit_start == 100.0
    assert monitor.last_missing_time is None
    assert monitor.last_observation_status == "UNKNOWN"
    assert monitor.last_observation_time == 200.0


def test_short_restart_restores_only_after_fresh_presence(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    first_monitor = _make_monitor(tmp_path, state_path=state_path)
    first_monitor.record_presence_observation(True, observed_at=100.0)
    first_monitor.record_presence_observation(True, observed_at=150.0)

    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "continuous_sit_start": 100.0,
        "last_presence_time": 150.0,
    }

    with patch("src.manager.manager_main.time.time", return_value=200.0):
        restarted_monitor = _make_monitor(tmp_path, state_path=state_path)

    assert restarted_monitor.continuous_sit_start is None
    restarted_monitor.record_presence_observation(True, observed_at=200.0)

    assert restarted_monitor.continuous_sit_start == 100.0
    assert restarted_monitor.last_presence_time == 200.0


def test_restart_at_grace_boundary_does_not_restore_stale_session(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 100.0,
                "last_presence_time": 200.0,
            }
        ),
        encoding="utf-8",
    )

    with patch("src.manager.manager_main.time.time", return_value=320.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    monitor.record_presence_observation(True, observed_at=320.0)

    assert monitor.continuous_sit_start == 320.0


def test_clock_rollback_after_state_load_does_not_restore_session(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 50.0,
                "last_presence_time": 100.0,
            }
        ),
        encoding="utf-8",
    )

    with patch("src.manager.manager_main.time.time", return_value=150.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    monitor.record_presence_observation(True, observed_at=140.0)

    assert monitor.continuous_sit_start == 140.0


def test_clock_rollback_after_unknown_does_not_restore_candidate(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 50.0,
                "last_presence_time": 100.0,
            }
        ),
        encoding="utf-8",
    )

    with patch("src.manager.manager_main.time.time", return_value=150.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    monitor.record_presence_observation(None, observed_at=210.0)
    monitor.record_presence_observation(True, observed_at=160.0)

    assert monitor.continuous_sit_start == 160.0


def test_clock_rollback_absence_invalidates_recovery_candidate(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 50.0,
                "last_presence_time": 100.0,
            }
        ),
        encoding="utf-8",
    )

    with patch("src.manager.manager_main.time.time", return_value=150.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    monitor.record_presence_observation(False, observed_at=140.0)
    assert not state_path.exists()

    monitor.record_presence_observation(True, observed_at=160.0)

    assert monitor.continuous_sit_start == 160.0


def test_clock_rollback_restarts_active_session_at_current_observation(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.record_presence_observation(True, observed_at=50.0)
    monitor.record_presence_observation(True, observed_at=200.0)

    monitor.record_presence_observation(True, observed_at=150.0)

    assert monitor.continuous_sit_start == 150.0
    assert monitor.last_presence_time == 150.0


@pytest.mark.parametrize(
    "state_payload",
    [
        "{not-json",
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": float("nan"),
                "last_presence_time": 200.0,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 250.0,
                "last_presence_time": 200.0,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 100.0,
                "last_presence_time": 401.0,
            }
        ),
    ],
    ids=("corrupt", "non-finite", "start-after-presence", "future"),
)
def test_invalid_restart_state_is_ignored(state_payload, tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(state_payload, encoding="utf-8")

    with patch("src.manager.manager_main.time.time", return_value=400.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    assert monitor.continuous_sit_start is None
    monitor.record_presence_observation(True, observed_at=400.0)
    assert monitor.continuous_sit_start == 400.0


def test_atomic_state_write_failure_does_not_escape_monitor(tmp_path, capsys):
    state_path = tmp_path / "focus-presence-state.json"
    monitor = _make_monitor(tmp_path, state_path=state_path)

    with patch("src.manager.manager_main.os.replace", side_effect=OSError("replace failed")):
        monitor.record_presence_observation(True, observed_at=100.0)

    assert monitor.continuous_sit_start == 100.0
    assert not state_path.exists()
    assert "replace failed" in capsys.readouterr().err


def test_state_load_failure_does_not_escape_monitor(tmp_path, capsys):
    state_path = tmp_path / "focus-presence-state.json"

    with patch(
        "src.manager.manager_main.Path.exists",
        side_effect=OSError("state lookup failed"),
    ):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    assert monitor.continuous_sit_start is None
    assert "state lookup failed" in capsys.readouterr().err


def test_run_task_records_unknown_when_capture_cycle_raises_before_observation(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.record_presence_observation(True, observed_at=100.0)
    monitor.record_presence_observation(False, observed_at=110.0)

    with (
        patch(
            "src.manager.manager_main.get_location",
            side_effect=RuntimeError("location unavailable"),
        ),
        patch("src.manager.manager_main.time.time", return_value=200.0),
    ):
        monitor.run_task()

    assert monitor.continuous_sit_start == 100.0
    assert monitor.last_missing_time is None
    assert monitor.last_observation_status == "UNKNOWN"
    assert monitor.last_observation_time == 200.0

    monitor.record_presence_observation(False, observed_at=231.0)
    assert monitor.continuous_sit_start == 100.0
    assert monitor.last_missing_time == 231.0


def test_run_task_passes_pre_captured_frame_to_photo_pipeline(tmp_path):
    frame = np.full((4, 4, 3), 23, dtype=np.uint8)
    monitor = _make_monitor(tmp_path)

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch(
            "src.manager.manager_main.take_photo",
            return_value=(None, None),
        ) as mock_take_photo,
        patch("src.manager.manager_main.time.time", return_value=200.0),
    ):
        monitor.run_task(pre_captured_frame=frame)

    mock_take_photo.assert_called_once()
    assert mock_take_photo.call_args.args == (
        monitor.camera,
        0.0,
        0.0,
        str(tmp_path),
    )
    assert mock_take_photo.call_args.kwargs.keys() == {"pre_captured_frame"}
    assert mock_take_photo.call_args.kwargs["pre_captured_frame"] is frame


def test_run_task_without_frame_keeps_legacy_photo_capture_call(tmp_path):
    monitor = _make_monitor(tmp_path)

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch(
            "src.manager.manager_main.take_photo",
            return_value=(None, None),
        ) as mock_take_photo,
        patch("src.manager.manager_main.time.time", return_value=200.0),
    ):
        monitor.run_task()

    mock_take_photo.assert_called_once_with(
        monitor.camera,
        0.0,
        0.0,
        str(tmp_path),
    )


def test_monitor_capture_cycle_uses_a_copy_of_latest_published_frame():
    published_frame = np.full((4, 4, 3), 41, dtype=np.uint8)
    received_frames = []

    class RecordingMonitor:
        def run_task(self, *, pre_captured_frame):
            received_frames.append(pre_captured_frame)

    original_monitor = server.state.monitor
    original_frame = server.state.latest_frame
    original_paths = server.state.paths
    try:
        server.state.monitor = RecordingMonitor()
        server.state.latest_frame = published_frame
        server.state.paths = {}

        server.run_monitor_capture_cycle()
        published_frame.fill(0)

        assert len(received_frames) == 1
        assert received_frames[0] is not published_frame
        assert np.all(received_frames[0] == 41)
    finally:
        server.state.monitor = original_monitor
        server.state.latest_frame = original_frame
        server.state.paths = original_paths


def test_monitor_capture_cycle_without_published_frame_records_unknown_without_camera_read(
    tmp_path,
):
    class ReadFailingCamera:
        def read(self):
            raise AssertionError("monitor must not read the physical camera")

    monitor = _make_monitor(tmp_path)
    monitor.camera = ReadFailingCamera()
    monitor.continuous_sit_start = 100.0
    original_monitor = server.state.monitor
    original_frame = server.state.latest_frame
    original_paths = server.state.paths
    try:
        server.state.monitor = monitor
        server.state.latest_frame = None
        server.state.paths = {}

        with (
            patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
            patch(
                "src.manager.take_photo.take_a_photo.capture_best_photo",
                side_effect=AssertionError("monitor must not capture a fallback frame"),
            ) as mock_capture,
            patch("src.manager.manager_main.time.time", return_value=200.0),
        ):
            server.run_monitor_capture_cycle()

        mock_capture.assert_not_called()
        assert monitor.continuous_sit_start == 100.0
        assert monitor.last_observation_status == "UNKNOWN"
        assert monitor.last_missing_time is None
    finally:
        server.state.monitor = original_monitor
        server.state.latest_frame = original_frame
        server.state.paths = original_paths


@pytest.mark.parametrize("new_screenshot_path", [None, ""])
def test_run_task_preserves_latest_media_when_present_capture_paths_are_empty(
    tmp_path,
    new_screenshot_path,
):
    monitor = _make_monitor(tmp_path)
    monitor.paths.update(
        {
            "photo": "previous-photo.jpg",
            "screenshot": "previous-screenshot.jpg",
        }
    )

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(True, None)),
        patch(
            "src.manager.manager_main.take_and_save_screenshots",
            return_value=new_screenshot_path,
        ),
        patch("src.manager.manager_main.time.time", return_value=200.0),
    ):
        monitor.run_task()

    assert monitor.paths == {
        "photo": "previous-photo.jpg",
        "screenshot": "previous-screenshot.jpg",
    }
    assert monitor.continuous_sit_start == 200.0
    assert monitor.last_presence_time == 200.0
    assert monitor.last_observation_status == "PRESENT"


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


@pytest.mark.parametrize(
    (
        "observation_status",
        "heartbeat",
        "expected_detection_status",
        "expected_is_sitting",
        "expected_duration_seconds",
    ),
    [
        ("PRESENT", 590.0, "present", True, 500),
        ("ABSENT", 590.0, "absent", True, 300),
        ("UNKNOWN", 590.0, "unknown", True, 300),
        ("PRESENT", 100.0, "stale", False, 300),
    ],
    ids=("present", "absent", "unknown", "stale"),
)
def test_get_sedentary_stats_reports_detection_state_and_trusted_duration(
    observation_status,
    heartbeat,
    expected_detection_status,
    expected_is_sitting,
    expected_duration_seconds,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            last_presence_time=400.0,
            last_observation_status=observation_status,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=heartbeat,
            monitor_stale_timeout=2 * 60,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": expected_detection_status,
            "is_sitting": expected_is_sitting,
            "duration_seconds": expected_duration_seconds,
            "duration_minutes": expected_duration_seconds // 60,
            "threshold_minutes": 20,
        }
        assert server.state.monitor.continuous_sit_start == 100.0
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    ("start", "last_presence", "observation_status"),
    [
        (float("nan"), 400.0, "UNKNOWN"),
        (700.0, 700.0, "PRESENT"),
        (100.0, float("inf"), "ABSENT"),
        (100.0, 601.0, "UNKNOWN"),
        (100.0, 601.0, "PRESENT"),
    ],
    ids=(
        "non-finite-start",
        "future-start",
        "non-finite-presence",
        "future-presence-frozen",
        "future-presence-live",
    ),
)
def test_get_sedentary_stats_rejects_untrusted_duration_timestamps(
    start,
    last_presence,
    observation_status,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=start,
            last_presence_time=last_presence,
            last_observation_status=observation_status,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=590.0,
            monitor_stale_timeout=2 * 60,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result["duration_seconds"] == 0
        assert result["duration_minutes"] == 0
        assert result["is_sitting"] is False
    finally:
        server.state.monitor = original_monitor
