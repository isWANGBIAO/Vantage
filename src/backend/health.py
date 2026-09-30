"""Sedentary-health statistics from persisted focus/presence state."""

import math
import time

from fastapi import APIRouter

from . import runtime as _runtime

router = APIRouter()

def _is_finite_nonnegative_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )

@router.get("/api/health/sedentary")
def get_sedentary_stats():
    """Returns the current continuous sitting duration from the monitor."""
    try:
        monitor = _runtime.state.monitor
        if not monitor:
            return {"status": "inactive"}

        now = time.time()
        snapshot_provider = getattr(monitor, "get_sedentary_snapshot", None)
        if callable(snapshot_provider):
            timer_snapshot = snapshot_provider(now=now)
            detection_status = timer_snapshot.get("detection_status", "unknown")
            focus_duration = timer_snapshot.get("focus_duration_seconds", 0)
            away_duration = timer_snapshot.get("away_duration_seconds", 0)
            active_timer = timer_snapshot.get("active_timer", "none")
            has_focus_session = timer_snapshot.get("has_focus_session", False)
            snapshot_is_valid = (
                detection_status in {"present", "absent", "unknown", "stale"}
                and _is_finite_nonnegative_number(focus_duration)
                and _is_finite_nonnegative_number(away_duration)
                and active_timer in {"focus", "away", "none"}
                and isinstance(has_focus_session, bool)
            )
            if not snapshot_is_valid:
                detection_status = "unknown"
                focus_duration = 0
                away_duration = 0
                active_timer = "none"
                has_focus_session = False

            threshold_seconds = timer_snapshot.get("sedentary_threshold", 0)
            threshold_minutes = (
                int(threshold_seconds // 60)
                if _is_finite_nonnegative_number(threshold_seconds)
                else 0
            )
            duration_sec = int(focus_duration)
            away_duration_sec = int(away_duration)
            return {
                "status": "active",
                "detection_status": detection_status,
                "is_sitting": (
                    has_focus_session and detection_status != "stale"
                ),
                "duration_minutes": int(duration_sec // 60),
                "duration_seconds": duration_sec,
                "away_duration_seconds": away_duration_sec,
                "active_timer": active_timer,
                "threshold_minutes": threshold_minutes,
            }

        monitor_snapshot = vars(monitor).copy()
        heartbeat = monitor_snapshot.get("last_monitor_heartbeat")
        stale_timeout = monitor_snapshot.get("monitor_stale_timeout", 120)
        last_observation_time = monitor_snapshot.get("last_observation_time")
        heartbeat_is_valid = (
            _is_finite_nonnegative_number(heartbeat)
            and heartbeat <= now
        )
        stale_timeout_is_valid = _is_finite_nonnegative_number(stale_timeout)
        observation_is_current = (
            heartbeat_is_valid
            and _is_finite_nonnegative_number(last_observation_time)
            and heartbeat <= last_observation_time <= now
        )
        heartbeat_is_stale = (
            heartbeat_is_valid
            and stale_timeout_is_valid
            and (now - heartbeat) >= stale_timeout
        )

        observed_status = str(
            monitor_snapshot.get("last_observation_status") or ""
        ).lower()
        if not heartbeat_is_valid or not stale_timeout_is_valid:
            detection_status = "unknown"
        elif heartbeat_is_stale:
            detection_status = "stale"
        elif not observation_is_current:
            detection_status = "unknown"
        elif observed_status in {"present", "absent", "unknown"}:
            detection_status = observed_status
        else:
            detection_status = "unknown"

        start = monitor_snapshot.get("continuous_sit_start")
        last_presence = monitor_snapshot.get("last_presence_time")
        trusted_end = (
            now
            if detection_status == "present"
            else last_presence
        )
        has_trusted_session = (
            _is_finite_nonnegative_number(start)
            and _is_finite_nonnegative_number(last_presence)
            and _is_finite_nonnegative_number(trusted_end)
            and start <= last_presence <= now
            and start <= trusted_end <= now
        )
        duration_sec = int(trusted_end - start) if has_trusted_session else 0

        threshold_seconds = monitor_snapshot.get("sedentary_threshold", 0)
        threshold_minutes = (
            int(threshold_seconds // 60)
            if _is_finite_nonnegative_number(threshold_seconds)
            else 0
        )
        return {
            "status": "active",
            "detection_status": detection_status,
            "is_sitting": has_trusted_session and detection_status != "stale",
            "duration_minutes": int(duration_sec // 60),
            "duration_seconds": int(duration_sec),
            "away_duration_seconds": 0,
            "active_timer": "focus" if has_trusted_session else "none",
            "threshold_minutes": threshold_minutes,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
