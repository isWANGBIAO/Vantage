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


def _record(monitor, status, observed_at):
    monitor.record_presence_observation(status, observed_at=observed_at)
    return (
        monitor.focus_elapsed_seconds,
        monitor.away_elapsed_seconds,
        monitor.active_timer,
        monitor.active_segment_started_at,
    )


def test_present_absent_present_counts_only_focus_and_never_moves_focus_backward(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)

    assert _record(monitor, True, 100.0) == (0.0, 0.0, "focus", 100.0)
    assert _record(monitor, False, 110.0) == (10.0, 0.0, "away", 110.0)
    assert _record(monitor, False, 190.0) == (10.0, 80.0, "away", 190.0)
    assert _record(monitor, True, 200.0) == (10.0, 0.0, "focus", 200.0)
    assert _record(monitor, True, 250.0) == (60.0, 0.0, "focus", 250.0)
    assert monitor.continuous_sit_start == 100.0


def test_present_unknown_present_pauses_without_counting_unknown_gap(tmp_path):
    monitor = _make_monitor(tmp_path)

    _record(monitor, True, 100.0)
    assert _record(monitor, None, 150.0) == (50.0, 0.0, None, None)
    assert monitor.last_trusted_observation_status == monitor.PRESENT
    assert monitor.last_trusted_observation_time == 100.0

    assert _record(monitor, True, 200.0) == (50.0, 0.0, "focus", 200.0)
    assert _record(monitor, True, 250.0) == (100.0, 0.0, "focus", 250.0)


def test_absent_unknown_absent_freezes_then_resumes_trusted_away_time(tmp_path):
    monitor = _make_monitor(tmp_path)

    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    assert _record(monitor, None, 200.0) == (10.0, 90.0, None, None)
    assert monitor.away_start_time == 110.0
    assert monitor.last_missing_time == 110.0

    assert _record(monitor, False, 250.0) == (10.0, 90.0, "away", 250.0)
    assert _record(monitor, False, 279.999) == (
        10.0,
        pytest.approx(119.999),
        "away",
        279.999,
    )
    assert monitor.continuous_sit_start == 100.0

    assert _record(monitor, False, 280.0) == (0.0, 120.0, "away", 280.0)
    assert monitor.continuous_sit_start is None
    assert monitor.away_start_time == 110.0


def test_exact_away_grace_boundary_resets_focus_but_keeps_away_timer(tmp_path):
    monitor = _make_monitor(tmp_path)

    _record(monitor, True, 10.0)
    _record(monitor, True, 20.0)
    _record(monitor, False, 30.0)
    _record(monitor, False, 149.999)

    assert monitor.focus_elapsed_seconds == 20.0
    assert monitor.away_elapsed_seconds == pytest.approx(119.999)
    assert monitor.continuous_sit_start == 10.0

    _record(monitor, False, 150.0)

    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 120.0
    assert monitor.continuous_sit_start is None
    assert monitor.active_timer == "away"
    assert monitor.active_segment_started_at == 150.0


def test_only_one_timer_can_be_active_for_every_presence_transition(tmp_path):
    monitor = _make_monitor(tmp_path)
    transitions = [
        (True, 100.0, "focus"),
        (False, 110.0, "away"),
        (None, 120.0, None),
        (False, 130.0, "away"),
        (True, 140.0, "focus"),
        (None, 150.0, None),
    ]

    for observation, observed_at, expected_timer in transitions:
        _record(monitor, observation, observed_at)
        assert monitor.active_timer == expected_timer
        assert (monitor.active_segment_started_at is not None) == (
            expected_timer is not None
        )
        assert monitor.active_timer not in {"focus+away", "away+focus"}


def test_sedentary_notification_excludes_away_time(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.sedentary_threshold = 100.0
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    _record(monitor, True, 200.0)

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(True, None)),
        patch(
            "src.manager.manager_main.take_and_save_screenshots",
            return_value=None,
        ),
        patch(
            "src.manager.manager_main.time.time",
            side_effect=[250.0, 250.0],
        ),
        patch("src.manager.manager_main.threading.Thread") as thread_class,
    ):
        assert monitor.run_task() == monitor.PRESENT

    assert monitor.focus_elapsed_seconds == 60.0
    thread_class.assert_not_called()


def test_stale_gap_freezes_at_cutoff_and_resumes_without_reset_or_catch_up(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    monitor.monitor_stale_timeout = 120.0
    _record(monitor, True, 100.0)
    _record(monitor, True, 150.0)
    monitor.last_monitor_heartbeat = 150.0

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(True, None)),
        patch(
            "src.manager.manager_main.take_and_save_screenshots",
            return_value=None,
        ),
        patch(
            "src.manager.manager_main.time.time",
            side_effect=[400.0, 400.0],
        ),
    ):
        assert monitor.run_task() == monitor.PRESENT

    assert monitor.continuous_sit_start == 100.0
    assert monitor.focus_elapsed_seconds == 170.0
    assert monitor.active_timer == "focus"
    assert monitor.active_segment_started_at == 400.0

    _record(monitor, True, 450.0)
    assert monitor.focus_elapsed_seconds == 220.0


def test_run_task_excludes_capture_latency_without_relying_on_api_polling(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    _record(monitor, True, 150.0)
    monitor.last_monitor_heartbeat = 150.0

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(True, None)),
        patch(
            "src.manager.manager_main.take_and_save_screenshots",
            return_value=None,
        ),
        patch(
            "src.manager.manager_main.time.time",
            side_effect=[200.0, 260.0],
        ),
    ):
        assert monitor.run_task() == monitor.PRESENT

    assert monitor.continuous_sit_start == 100.0
    assert monitor.focus_elapsed_seconds == 100.0
    assert monitor.active_timer == "focus"
    assert monitor.active_segment_started_at == 260.0


def test_run_task_reports_grace_from_trusted_away_time_after_unknown_gap(
    tmp_path,
    capsys,
):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    _record(monitor, None, 200.0)
    monitor.last_monitor_heartbeat = 200.0

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(False, None)),
        patch(
            "src.manager.manager_main.time.time",
            side_effect=[231.0, 231.0],
        ),
    ):
        assert monitor.run_task() == monitor.ABSENT

    assert monitor.continuous_sit_start == 100.0
    assert monitor.away_elapsed_seconds == 90.0
    assert "Grace period: 30s left" in capsys.readouterr().err


def test_stale_cutoff_that_completes_away_grace_clears_only_focus_session(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    monitor.monitor_stale_timeout = 120.0
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    monitor.last_monitor_heartbeat = 110.0

    with (
        patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
        patch("src.manager.manager_main.take_photo", return_value=(True, None)),
        patch(
            "src.manager.manager_main.take_and_save_screenshots",
            return_value=None,
        ),
        patch(
            "src.manager.manager_main.time.time",
            side_effect=[300.0, 300.0],
        ),
    ):
        assert monitor.run_task() == monitor.PRESENT

    assert monitor.continuous_sit_start == 300.0
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 0.0
    assert monitor.active_timer == "focus"
    assert monitor.active_segment_started_at == 300.0


def test_clock_rollback_clears_both_accumulators_and_starts_fresh_mode(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    _record(monitor, False, 150.0)

    assert monitor.focus_elapsed_seconds == 10.0
    assert monitor.away_elapsed_seconds == 40.0
    assert state_path.exists()

    _record(monitor, False, 120.0)

    assert monitor.continuous_sit_start is None
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 0.0
    assert monitor.away_start_time == 120.0
    assert monitor.active_timer == "away"
    assert monitor._recovery_candidate is None


@pytest.mark.parametrize(
    "invalid_observed_at",
    [float("nan"), float("inf"), -1.0, True, "200"],
    ids=("nan", "infinite", "negative", "bool", "string"),
)
def test_invalid_observation_time_clears_all_activity_fail_closed(
    invalid_observed_at,
    tmp_path,
):
    state_path = tmp_path / "focus-presence-state.json"
    monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)
    _record(monitor, False, 150.0)

    status = monitor.record_presence_observation(
        True,
        observed_at=invalid_observed_at,
    )

    assert status == monitor.UNKNOWN
    assert monitor.continuous_sit_start is None
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 0.0
    assert monitor.away_start_time is None
    assert monitor.active_timer is None
    assert monitor.active_segment_started_at is None
    assert monitor.last_observation_status is None
    assert monitor.last_observation_time is None
    assert not state_path.exists()


def test_corrupt_in_memory_accumulator_is_cleared_before_fresh_observation(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    monitor.away_elapsed_seconds = float("nan")

    assert monitor.record_presence_observation(True, observed_at=200.0) == (
        monitor.PRESENT
    )
    assert monitor.continuous_sit_start == 200.0
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 0.0
    assert monitor.active_timer == "focus"
    assert monitor.active_segment_started_at == 200.0


def test_unknown_boundary_that_completes_away_grace_clears_only_focus(tmp_path):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    _record(monitor, False, 110.0)

    _record(monitor, None, 230.0)

    assert monitor.continuous_sit_start is None
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 120.0
    assert monitor.away_start_time == 110.0
    assert monitor.active_timer is None
    assert monitor.last_trusted_observation_status == monitor.ABSENT


def test_v2_state_persists_dual_accumulators_and_paused_mode(tmp_path):
    state_path = tmp_path / "focus-presence-state.json"
    monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(monitor, True, 100.0)
    _record(monitor, True, 150.0)
    _record(monitor, False, 160.0)
    _record(monitor, None, 200.0)

    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert payload == {
        "version": 2,
        "saved_at": 200.0,
        "continuous_sit_start": 100.0,
        "focus_elapsed_seconds": 60.0,
        "away_elapsed_seconds": 40.0,
        "away_start_time": 160.0,
        "active_timer": None,
        "active_segment_started_at": None,
        "last_presence_time": 150.0,
        "last_missing_time": 160.0,
        "last_trusted_observation_status": "ABSENT",
        "last_trusted_observation_time": 160.0,
        "last_observation_status": "UNKNOWN",
        "last_observation_time": 200.0,
    }


def test_v1_state_migrates_to_focus_candidate_without_counting_restart_gap(
    tmp_path,
):
    state_path = tmp_path / "focus-presence-state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuous_sit_start": 100.0,
                "last_presence_time": 150.0,
            }
        ),
        encoding="utf-8",
    )

    with patch("src.manager.manager_main.time.time", return_value=200.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    assert monitor.continuous_sit_start is None
    _record(monitor, None, 205.0)
    assert monitor._recovery_candidate is not None

    _record(monitor, True, 210.0)
    assert monitor.continuous_sit_start == 100.0
    assert monitor.focus_elapsed_seconds == 50.0
    assert monitor.active_timer == "focus"
    assert monitor.active_segment_started_at == 210.0

    _record(monitor, True, 230.0)
    assert monitor.focus_elapsed_seconds == 70.0
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 2


def test_v2_focus_candidate_restores_only_on_matching_trusted_observation(
    tmp_path,
):
    state_path = tmp_path / "focus-presence-state.json"
    first_monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(first_monitor, True, 100.0)
    _record(first_monitor, True, 150.0)

    with patch("src.manager.manager_main.time.time", return_value=180.0):
        restarted = _make_monitor(tmp_path, state_path=state_path)

    assert restarted.continuous_sit_start is None
    _record(restarted, None, 185.0)
    assert restarted._recovery_candidate is not None

    _record(restarted, True, 200.0)
    assert restarted.continuous_sit_start == 100.0
    assert restarted.focus_elapsed_seconds == 50.0
    assert restarted.active_timer == "focus"
    assert restarted.active_segment_started_at == 200.0

    _record(restarted, True, 220.0)
    assert restarted.focus_elapsed_seconds == 70.0


def test_v2_away_candidate_restores_only_on_matching_trusted_observation(
    tmp_path,
):
    state_path = tmp_path / "focus-presence-state.json"
    first_monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(first_monitor, True, 100.0)
    _record(first_monitor, False, 110.0)
    _record(first_monitor, False, 150.0)

    with patch("src.manager.manager_main.time.time", return_value=180.0):
        restarted = _make_monitor(tmp_path, state_path=state_path)

    assert restarted.continuous_sit_start is None
    _record(restarted, None, 185.0)
    assert restarted._recovery_candidate is not None

    _record(restarted, False, 200.0)
    assert restarted.continuous_sit_start == 100.0
    assert restarted.focus_elapsed_seconds == 10.0
    assert restarted.away_elapsed_seconds == 40.0
    assert restarted.away_start_time == 110.0
    assert restarted.active_timer == "away"
    assert restarted.active_segment_started_at == 200.0

    _record(restarted, False, 220.0)
    assert restarted.away_elapsed_seconds == 60.0


@pytest.mark.parametrize(
    ("saved_mode", "fresh_observation", "expected_active_timer"),
    [
        ("focus", False, "away"),
        ("away", True, "focus"),
    ],
)
def test_recovery_candidate_mismatch_starts_fresh_without_restoring_saved_time(
    saved_mode,
    fresh_observation,
    expected_active_timer,
    tmp_path,
):
    state_path = tmp_path / "focus-presence-state.json"
    first_monitor = _make_monitor(tmp_path, state_path=state_path)
    _record(first_monitor, True, 100.0)
    if saved_mode == "focus":
        _record(first_monitor, True, 150.0)
    else:
        _record(first_monitor, False, 110.0)
        _record(first_monitor, False, 150.0)

    with patch("src.manager.manager_main.time.time", return_value=180.0):
        restarted = _make_monitor(tmp_path, state_path=state_path)

    _record(restarted, fresh_observation, 200.0)

    assert restarted.focus_elapsed_seconds == 0.0
    assert restarted.away_elapsed_seconds == 0.0
    assert restarted.active_timer == expected_active_timer
    if fresh_observation:
        assert restarted.continuous_sit_start == 200.0
    else:
        assert restarted.continuous_sit_start is None
        assert restarted.away_start_time == 200.0


def _valid_v2_focus_payload():
    return {
        "version": 2,
        "saved_at": 150.0,
        "continuous_sit_start": 100.0,
        "focus_elapsed_seconds": 50.0,
        "away_elapsed_seconds": 0.0,
        "away_start_time": None,
        "active_timer": "focus",
        "active_segment_started_at": 150.0,
        "last_presence_time": 150.0,
        "last_missing_time": None,
        "last_trusted_observation_status": "PRESENT",
        "last_trusted_observation_time": 150.0,
        "last_observation_status": "PRESENT",
        "last_observation_time": 150.0,
    }


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"focus_elapsed_seconds": float("nan")},
        {"focus_elapsed_seconds": True},
        {"away_elapsed_seconds": float("inf")},
        {"away_elapsed_seconds": -1.0},
        {"saved_at": 181.0},
        {"saved_at": 149.0},
        {"continuous_sit_start": False},
        {"active_timer": "focus+away"},
        {"active_segment_started_at": None},
        {"active_timer": None},
        {
            "last_trusted_observation_status": "ABSENT",
            "away_start_time": 150.0,
            "last_missing_time": 150.0,
        },
        {"last_trusted_observation_time": 151.0},
        {"last_observation_time": 151.0},
        {"last_presence_time": 151.0},
        {
            "away_elapsed_seconds": 120.0,
            "away_start_time": 30.0,
            "last_missing_time": 30.0,
            "last_trusted_observation_status": "ABSENT",
        },
        {
            "active_timer": "away",
            "away_elapsed_seconds": 40.0,
            "last_trusted_observation_status": "ABSENT",
        },
    ],
    ids=(
        "nan-focus",
        "bool-focus",
        "infinite-away",
        "negative-away",
        "future-saved-at",
        "saved-before-observation",
        "bool-session-start",
        "invalid-active-mode",
        "missing-active-anchor",
        "orphan-active-anchor",
        "mode-mismatch",
        "trusted-after-observation",
        "observation-after-save",
        "presence-after-save",
        "expired-away-keeps-focus",
        "away-mode-without-away-start",
    ),
)
def test_invalid_v2_state_is_rejected_and_removed(invalid_fields, tmp_path):
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(_valid_v2_focus_payload()), encoding="utf-8")
    with patch("src.manager.manager_main.time.time", return_value=180.0):
        valid_monitor = _make_monitor(tmp_path, state_path=valid_path)
    assert valid_monitor._recovery_candidate is not None

    state_path = tmp_path / "invalid.json"
    payload = _valid_v2_focus_payload()
    payload.update(invalid_fields)
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("src.manager.manager_main.time.time", return_value=180.0):
        monitor = _make_monitor(tmp_path, state_path=state_path)

    assert monitor._recovery_candidate is None
    assert not state_path.exists()


def _get_sedentary_api_result(monitor, *, now):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = monitor
        with patch("src.server.time.time", return_value=now):
            return server.get_sedentary_stats()
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    (
        "observations",
        "heartbeat",
        "now",
        "expected_detection",
        "expected_sitting",
        "expected_focus",
        "expected_away",
        "expected_timer",
    ),
    [
        (
            [(True, 100.0), (True, 150.0)],
            150.0,
            180.0,
            "present",
            True,
            80,
            0,
            "focus",
        ),
        (
            [(True, 100.0), (False, 110.0)],
            110.0,
            150.0,
            "absent",
            True,
            10,
            40,
            "away",
        ),
        (
            [(True, 100.0), (False, 110.0), (False, 230.0)],
            230.0,
            250.0,
            "absent",
            False,
            0,
            140,
            "away",
        ),
        (
            [(True, 100.0), (None, 150.0)],
            150.0,
            180.0,
            "unknown",
            True,
            50,
            0,
            "focus",
        ),
        (
            [(True, 100.0), (False, 110.0), (None, 150.0)],
            150.0,
            180.0,
            "unknown",
            True,
            10,
            40,
            "away",
        ),
        (
            [(False, 100.0), (None, 250.0)],
            250.0,
            280.0,
            "unknown",
            False,
            0,
            150,
            "away",
        ),
    ],
    ids=(
        "present",
        "absent-grace",
        "absent-confirmed",
        "unknown-from-focus",
        "unknown-from-away-grace",
        "unknown-from-away-confirmed",
    ),
)
def test_get_sedentary_stats_reports_dual_trusted_timers(
    observations,
    heartbeat,
    now,
    expected_detection,
    expected_sitting,
    expected_focus,
    expected_away,
    expected_timer,
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    for observation, observed_at in observations:
        _record(monitor, observation, observed_at)
    monitor.last_monitor_heartbeat = heartbeat

    result = _get_sedentary_api_result(monitor, now=now)

    assert result == {
        "status": "active",
        "detection_status": expected_detection,
        "is_sitting": expected_sitting,
        "duration_seconds": expected_focus,
        "duration_minutes": expected_focus // 60,
        "away_duration_seconds": expected_away,
        "active_timer": expected_timer,
        "threshold_minutes": 20,
    }


@pytest.mark.parametrize(
    (
        "observations",
        "heartbeat",
        "now",
        "expected_focus",
        "expected_away",
        "expected_timer",
    ),
    [
        ([(True, 100.0), (True, 150.0)], 150.0, 300.0, 170, 0, "focus"),
        ([(True, 100.0), (False, 110.0)], 110.0, 250.0, 0, 120, "away"),
    ],
    ids=("stale-from-focus", "stale-from-away"),
)
def test_get_sedentary_stats_freezes_stale_timer_at_cutoff(
    observations,
    heartbeat,
    now,
    expected_focus,
    expected_away,
    expected_timer,
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    for observation, observed_at in observations:
        _record(monitor, observation, observed_at)
    monitor.last_monitor_heartbeat = heartbeat

    first = _get_sedentary_api_result(monitor, now=now)
    later = _get_sedentary_api_result(monitor, now=now + 300.0)

    for result in (first, later):
        assert result["detection_status"] == "stale"
        assert result["is_sitting"] is False
        assert result["duration_seconds"] == expected_focus
        assert result["away_duration_seconds"] == expected_away
        assert result["active_timer"] == expected_timer
    assert monitor.active_timer is None
    assert monitor.active_segment_started_at is None


@pytest.mark.parametrize(
    ("heartbeat", "stale_timeout"),
    [
        (float("nan"), 120.0),
        (float("inf"), 120.0),
        (200.0, 120.0),
        (-1.0, 120.0),
        (150.0, float("nan")),
        (150.0, float("inf")),
        (150.0, -1.0),
    ],
    ids=(
        "nan-heartbeat",
        "infinite-heartbeat",
        "future-heartbeat",
        "negative-heartbeat",
        "nan-timeout",
        "infinite-timeout",
        "negative-timeout",
    ),
)
def test_get_sedentary_stats_freezes_focus_for_invalid_heartbeat_or_timeout(
    heartbeat,
    stale_timeout,
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    _record(monitor, True, 150.0)
    monitor.last_monitor_heartbeat = heartbeat
    monitor.monitor_stale_timeout = stale_timeout

    result = _get_sedentary_api_result(monitor, now=180.0)

    assert result["detection_status"] == "unknown"
    assert result["duration_seconds"] == 50
    assert result["away_duration_seconds"] == 0
    assert result["active_timer"] == "focus"
    assert result["is_sitting"] is True
    assert monitor.active_timer is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("focus_elapsed_seconds", float("nan")),
        ("focus_elapsed_seconds", True),
        ("focus_elapsed_seconds", -1.0),
        ("away_elapsed_seconds", float("inf")),
        ("active_segment_started_at", float("nan")),
        ("active_segment_started_at", 50.0),
        ("active_segment_started_at", 181.0),
        ("active_timer", "focus+away"),
    ],
    ids=(
        "nan-focus",
        "bool-focus",
        "negative-focus",
        "infinite-away",
        "nan-anchor",
        "anchor-before-observation",
        "future-anchor",
        "invalid-mode",
    ),
)
def test_get_sedentary_stats_fails_closed_for_invalid_timer_state(
    field,
    value,
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)
    _record(monitor, True, 150.0)
    monitor.last_monitor_heartbeat = 150.0
    setattr(monitor, field, value)

    result = _get_sedentary_api_result(monitor, now=180.0)

    assert result["detection_status"] == "unknown"
    assert result["duration_seconds"] == 0
    assert result["away_duration_seconds"] == 0
    assert result["active_timer"] == "none"
    assert result["is_sitting"] is False


def test_get_sedentary_stats_applies_exact_away_grace_while_polling(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.monitor_stale_timeout = 300.0
    _record(monitor, True, 10.0)
    _record(monitor, False, 30.0)
    monitor.last_monitor_heartbeat = 30.0

    before = _get_sedentary_api_result(monitor, now=149.999)
    assert before["away_duration_seconds"] == 119
    assert before["is_sitting"] is True
    assert monitor.continuous_sit_start == 10.0

    at_boundary = _get_sedentary_api_result(monitor, now=150.0)
    assert at_boundary["away_duration_seconds"] == 120
    assert at_boundary["is_sitting"] is False
    assert at_boundary["active_timer"] == "away"
    assert monitor.continuous_sit_start is None
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.active_timer == "away"
    assert monitor.active_segment_started_at == 150.0


def test_get_sedentary_stats_handles_stale_first_cycle_without_observation(
    tmp_path,
):
    monitor = _make_monitor(tmp_path)
    monitor.last_monitor_heartbeat = 100.0

    result = _get_sedentary_api_result(monitor, now=220.0)

    assert result == {
        "status": "active",
        "detection_status": "stale",
        "is_sitting": False,
        "duration_seconds": 0,
        "duration_minutes": 0,
        "away_duration_seconds": 0,
        "active_timer": "none",
        "threshold_minutes": 20,
    }


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


def test_observation_time_is_published_after_present_session_state(tmp_path):
    class CommitRecordingMonitor(Monitor):
        def __init__(self, *args, **kwargs):
            self.commit_snapshots = []
            super().__init__(*args, **kwargs)

        def __setattr__(self, name, value):
            if name == "last_observation_time" and value is not None:
                self.commit_snapshots.append(
                    {
                        "continuous_sit_start": self.continuous_sit_start,
                        "last_presence_time": self.last_presence_time,
                        "last_observation_status": self.last_observation_status,
                    }
                )
            super().__setattr__(name, value)

    monitor = CommitRecordingMonitor(
        camera=None,
        paths={},
        photos_path=str(tmp_path),
        screenshots_path=str(tmp_path),
    )

    monitor.record_presence_observation(True, observed_at=100.0)

    assert monitor.commit_snapshots == [
        {
            "continuous_sit_start": 100.0,
            "last_presence_time": 100.0,
            "last_observation_status": "PRESENT",
        }
    ]


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
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 120.0
    assert monitor.away_start_time == 110.0
    assert monitor.last_missing_time == 110.0
    assert monitor.last_observation_status == "ABSENT"
    assert monitor.last_observation_time == 230.0
    assert json.loads(state_path.read_text(encoding="utf-8"))[
        "away_elapsed_seconds"
    ] == 120.0


def test_unknown_observation_pauses_existing_absence_debounce(tmp_path):
    monitor = _make_monitor(tmp_path)
    monitor.record_presence_observation(True, observed_at=100.0)
    monitor.record_presence_observation(False, observed_at=110.0)

    monitor.record_presence_observation(None, observed_at=500.0)
    monitor.record_presence_observation(False, observed_at=501.0)

    assert monitor.continuous_sit_start is None
    assert monitor.focus_elapsed_seconds == 0.0
    assert monitor.away_elapsed_seconds == 390.0
    assert monitor.last_missing_time == 110.0
    assert monitor.active_segment_started_at == 501.0


def test_run_task_records_unknown_photo_result_without_starting_absence_debounce(tmp_path):
    monitor = _make_monitor(tmp_path)
    _record(monitor, True, 100.0)

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

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["continuous_sit_start"] == 100.0
    assert payload["focus_elapsed_seconds"] == 50.0
    assert payload["active_timer"] == "focus"
    assert payload["active_segment_started_at"] == 150.0

    with patch("src.manager.manager_main.time.time", return_value=200.0):
        restarted_monitor = _make_monitor(tmp_path, state_path=state_path)

    assert restarted_monitor.continuous_sit_start is None
    restarted_monitor.record_presence_observation(True, observed_at=200.0)

    assert restarted_monitor.continuous_sit_start == 100.0
    assert restarted_monitor.focus_elapsed_seconds == 50.0
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
    assert monitor.continuous_sit_start is None
    assert monitor.away_start_time == 140.0
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 2

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
    assert monitor.focus_elapsed_seconds == 10.0
    assert monitor.away_elapsed_seconds == 90.0
    assert monitor.last_missing_time == 110.0
    assert monitor.last_observation_status == "UNKNOWN"
    assert monitor.last_observation_time == 200.0

    monitor.record_presence_observation(False, observed_at=231.0)
    assert monitor.continuous_sit_start == 100.0
    assert monitor.away_elapsed_seconds == 90.0
    assert monitor.last_missing_time == 110.0


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
    _record(monitor, True, 100.0)
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


def test_run_task_pauses_and_resumes_sedentary_timer_after_stale_monitor_gap():
    with tempfile.TemporaryDirectory() as tmp_dir:
        monitor = Monitor(
            camera=None,
            paths={},
            photos_path=tmp_dir,
            screenshots_path=tmp_dir,
        )
        monitor.record_presence_observation(True, observed_at=100.0)
        monitor.record_presence_observation(True, observed_at=150.0)
        monitor.last_monitor_heartbeat = 150.0

        with (
            patch("src.manager.manager_main.get_location", return_value=(0.0, 0.0)),
            patch("src.manager.manager_main.take_photo", return_value=(True, "photo.jpg")),
            patch("src.manager.manager_main.take_and_save_screenshots", return_value="screenshot.jpg"),
            patch("src.manager.manager_main.time.time", return_value=600.0),
        ):
            monitor.run_task()

        assert monitor.continuous_sit_start == 100.0
        assert monitor.focus_elapsed_seconds == 170.0
        assert monitor.active_timer == "focus"
        assert monitor.active_segment_started_at == 600.0


@pytest.mark.parametrize(
    (
        "observation_status",
        "heartbeat",
        "last_observation_time",
        "expected_detection_status",
        "expected_is_sitting",
        "expected_duration_seconds",
    ),
    [
        ("PRESENT", 590.0, 590.0, "present", True, 500),
        ("ABSENT", 590.0, 590.0, "absent", True, 300),
        ("UNKNOWN", 590.0, 590.0, "unknown", True, 300),
        ("PRESENT", 100.0, 400.0, "stale", False, 300),
    ],
    ids=("present", "absent", "unknown", "stale"),
)
def test_get_sedentary_stats_reports_detection_state_and_trusted_duration(
    observation_status,
    heartbeat,
    last_observation_time,
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
            last_observation_time=last_observation_time,
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
            "away_duration_seconds": 0,
            "active_timer": "focus",
            "threshold_minutes": 20,
        }
        assert server.state.monitor.continuous_sit_start == 100.0
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    "heartbeat_attributes",
    [
        {"last_monitor_heartbeat": float("nan")},
        {"last_monitor_heartbeat": float("inf")},
        {"last_monitor_heartbeat": 700.0},
        {"last_monitor_heartbeat": -1.0},
        {},
    ],
    ids=("nan", "infinite", "future", "negative", "missing"),
)
def test_get_sedentary_stats_fails_closed_for_invalid_heartbeat(
    heartbeat_attributes,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            last_presence_time=400.0,
            last_observation_status="PRESENT",
            last_observation_time=590.0,
            sedentary_threshold=20 * 60,
            monitor_stale_timeout=2 * 60,
            **heartbeat_attributes,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": "unknown",
            "is_sitting": True,
            "duration_seconds": 300,
            "duration_minutes": 5,
            "away_duration_seconds": 0,
            "active_timer": "focus",
            "threshold_minutes": 20,
        }
        assert server.state.monitor.continuous_sit_start == 100.0
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    "stale_timeout",
    [float("nan"), float("inf"), -1.0],
    ids=("nan", "infinite", "negative"),
)
def test_get_sedentary_stats_fails_closed_for_invalid_stale_timeout(
    stale_timeout,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            last_presence_time=400.0,
            last_observation_status="PRESENT",
            last_observation_time=590.0,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=590.0,
            monitor_stale_timeout=stale_timeout,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": "unknown",
            "is_sitting": True,
            "duration_seconds": 300,
            "duration_minutes": 5,
            "away_duration_seconds": 0,
            "active_timer": "focus",
            "threshold_minutes": 20,
        }
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    "observation_attributes",
    [
        {},
        {"last_observation_time": float("nan")},
        {"last_observation_time": float("inf")},
        {"last_observation_time": 700.0},
        {"last_observation_time": 580.0},
    ],
    ids=("missing", "nan", "infinite", "future", "before-heartbeat"),
)
def test_get_sedentary_stats_fails_closed_until_current_observation_completes(
    observation_attributes,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            last_presence_time=400.0,
            last_observation_status="PRESENT",
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=590.0,
            monitor_stale_timeout=2 * 60,
            **observation_attributes,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": "unknown",
            "is_sitting": True,
            "duration_seconds": 300,
            "duration_minutes": 5,
            "away_duration_seconds": 0,
            "active_timer": "focus",
            "threshold_minutes": 20,
        }
        assert server.state.monitor.continuous_sit_start == 100.0
    finally:
        server.state.monitor = original_monitor


def test_get_sedentary_stats_does_not_reuse_present_status_after_stale_gap_reset():
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=None,
            last_presence_time=None,
            last_observation_status="PRESENT",
            last_observation_time=400.0,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=600.0,
            monitor_stale_timeout=2 * 60,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": "unknown",
            "is_sitting": False,
            "duration_seconds": 0,
            "duration_minutes": 0,
            "away_duration_seconds": 0,
            "active_timer": "none",
            "threshold_minutes": 20,
        }
    finally:
        server.state.monitor = original_monitor


@pytest.mark.parametrize(
    "heartbeat",
    [480.0, 479.0],
    ids=("timeout-boundary", "past-timeout"),
)
def test_get_sedentary_stats_prioritizes_stale_over_incomplete_observation(
    heartbeat,
):
    original_monitor = server.state.monitor
    try:
        server.state.monitor = SimpleNamespace(
            continuous_sit_start=100.0,
            last_presence_time=400.0,
            last_observation_status="PRESENT",
            last_observation_time=470.0,
            sedentary_threshold=20 * 60,
            last_monitor_heartbeat=heartbeat,
            monitor_stale_timeout=2 * 60,
        )

        with patch("src.server.time.time", return_value=600.0):
            result = server.get_sedentary_stats()

        assert result == {
            "status": "active",
            "detection_status": "stale",
            "is_sitting": False,
            "duration_seconds": 300,
            "duration_minutes": 5,
            "away_duration_seconds": 0,
            "active_timer": "focus",
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
            last_observation_time=590.0,
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
