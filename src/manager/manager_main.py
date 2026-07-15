from .take_photo.take_a_photo import take_photo
from .screenshot.take_a_screenshot import take_and_save_screenshots
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from .get_location import get_location


_PRE_CAPTURED_FRAME_UNSET = object()


class Monitor:
    PRESENCE_STATE_VERSION = 2
    LEGACY_PRESENCE_STATE_VERSION = 1
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"

    def __init__(self, camera, paths, photos_path, screenshots_path, state_path=None):
        self.camera = camera
        self.paths = paths
        self.photos_path = photos_path
        self.screenshots_path = screenshots_path
        self.state_path = Path(state_path) if state_path is not None else None

        base_dir = self.photos_path
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BASE_DIR: {base_dir}")
        knowledge_base = os.path.join(base_dir, "knowledge_base.json")
        if not os.path.exists(knowledge_base):
            with open(knowledge_base, "w") as f:
                json.dump({}, f)

        self._state_lock = threading.RLock()
        self.continuous_sit_start = None
        self.focus_elapsed_seconds = 0.0
        self.away_elapsed_seconds = 0.0
        self.away_start_time = None
        self.active_timer = None
        self.active_segment_started_at = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.last_presence_time = None
        self.last_trusted_observation_status = None
        self.last_trusted_observation_time = None
        self.last_observation_status = None
        self.last_observation_time = None
        self.sedentary_threshold = 20 * 60
        self.notification_interval = 5 * 60
        self.grace_period = 2 * 60
        self.last_monitor_heartbeat = None
        self.monitor_stale_timeout = self.grace_period
        self._recovery_candidate = None
        self._load_recovery_candidate()

    def reset_sedentary_state(self):
        with self._state_lock:
            self._reset_sedentary_state_locked()

    def _reset_sedentary_state_locked(self):
        self.continuous_sit_start = None
        self.focus_elapsed_seconds = 0.0
        self.away_elapsed_seconds = 0.0
        self.away_start_time = None
        self.active_timer = None
        self.active_segment_started_at = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.last_presence_time = None
        self.last_trusted_observation_status = None
        self.last_trusted_observation_time = None
        self.last_observation_status = None
        self.last_observation_time = None
        self._recovery_candidate = None
        self._remove_presence_state()

    def _reset_focus_session_locked(self):
        self.continuous_sit_start = None
        self.focus_elapsed_seconds = 0.0
        self.last_notification_time = None
        self.last_presence_time = None

    def _settle_active_segment_locked(self, settled_at):
        if self.active_timer is None:
            self.active_segment_started_at = None
            return

        segment_started_at = self.active_segment_started_at
        if (
            not self._is_finite_timestamp(segment_started_at)
            or settled_at < segment_started_at
        ):
            self._reset_sedentary_state_locked()
            return

        elapsed = float(settled_at - segment_started_at)
        if self.active_timer == "focus":
            self.focus_elapsed_seconds += elapsed
        elif self.active_timer == "away":
            self.away_elapsed_seconds += elapsed
        else:
            self._reset_sedentary_state_locked()
            return

        self.active_timer = None
        self.active_segment_started_at = None

    def _start_active_timer_locked(self, timer_name, started_at):
        if timer_name not in {"focus", "away"}:
            raise ValueError("active timer must be focus or away")
        self.active_timer = timer_name
        self.active_segment_started_at = started_at

    def _enforce_away_grace_locked(self):
        if (
            self.last_trusted_observation_status == self.ABSENT
            and self.away_elapsed_seconds >= self.grace_period
        ):
            self._reset_focus_session_locked()

    def _pause_for_stale_gap_locked(self, stale_cutoff):
        if self.active_timer is not None:
            safe_cutoff = max(stale_cutoff, self.active_segment_started_at)
            self._settle_active_segment_locked(safe_cutoff)
            self._enforce_away_grace_locked()
            self._persist_presence_state(saved_at=safe_cutoff)

    @staticmethod
    def _is_finite_timestamp(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        )

    def _remove_presence_state(self):
        if self.state_path is None:
            return
        try:
            self.state_path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"Focus presence state cleanup error: {exc}", file=sys.stderr)

    def _load_recovery_candidate(self):
        if self.state_path is None:
            return

        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            loaded_at = time.time()
            if payload.get("version") == self.LEGACY_PRESENCE_STATE_VERSION:
                candidate = self._parse_v1_recovery_candidate(payload, loaded_at)
            elif payload.get("version") == self.PRESENCE_STATE_VERSION:
                candidate = self._parse_v2_recovery_candidate(payload, loaded_at)
            else:
                candidate = None
            if candidate is None:
                raise ValueError("invalid or stale focus presence state")
            self._recovery_candidate = candidate
        except Exception as exc:
            self._recovery_candidate = None
            print(f"Focus presence state load error: {exc}", file=sys.stderr)
            self._remove_presence_state()

    def _parse_v1_recovery_candidate(self, payload, loaded_at):
        continuous_sit_start = payload.get("continuous_sit_start")
        last_presence_time = payload.get("last_presence_time")
        if not (
            self._is_finite_timestamp(continuous_sit_start)
            and self._is_finite_timestamp(last_presence_time)
            and continuous_sit_start <= last_presence_time <= loaded_at
            and 0 <= loaded_at - last_presence_time < self.grace_period
        ):
            return None

        return {
            "mode": "focus",
            "loaded_at": float(loaded_at),
            "saved_at": float(last_presence_time),
            "continuous_sit_start": float(continuous_sit_start),
            "focus_elapsed_seconds": float(
                last_presence_time - continuous_sit_start
            ),
            "away_elapsed_seconds": 0.0,
            "away_start_time": None,
            "last_presence_time": float(last_presence_time),
            "last_missing_time": None,
            "last_trusted_observation_status": self.PRESENT,
            "last_trusted_observation_time": float(last_presence_time),
            "last_observation_status": self.PRESENT,
            "last_observation_time": float(last_presence_time),
        }

    def _parse_v2_recovery_candidate(self, payload, loaded_at):
        saved_at = payload.get("saved_at")
        focus_elapsed = payload.get("focus_elapsed_seconds")
        away_elapsed = payload.get("away_elapsed_seconds")
        continuous_sit_start = payload.get("continuous_sit_start")
        away_start_time = payload.get("away_start_time")
        active_timer = payload.get("active_timer")
        active_segment_started_at = payload.get("active_segment_started_at")
        last_presence_time = payload.get("last_presence_time")
        last_missing_time = payload.get("last_missing_time")
        trusted_status = payload.get("last_trusted_observation_status")
        trusted_time = payload.get("last_trusted_observation_time")
        observation_status = payload.get("last_observation_status")
        observation_time = payload.get("last_observation_time")

        if not (
            self._is_finite_timestamp(saved_at)
            and self._is_finite_timestamp(focus_elapsed)
            and self._is_finite_timestamp(away_elapsed)
            and self._is_finite_timestamp(trusted_time)
            and self._is_finite_timestamp(observation_time)
            and trusted_status in {self.PRESENT, self.ABSENT}
            and observation_status in {self.PRESENT, self.ABSENT, self.UNKNOWN}
            and active_timer in {"focus", "away", None}
            and trusted_time <= observation_time <= saved_at <= loaded_at
            and 0 <= loaded_at - saved_at < self.grace_period
        ):
            return None

        if active_timer is None:
            if active_segment_started_at is not None:
                return None
        elif not (
            self._is_finite_timestamp(active_segment_started_at)
            and active_segment_started_at == saved_at
        ):
            return None

        optional_timestamps = (
            continuous_sit_start,
            away_start_time,
            last_presence_time,
            last_missing_time,
        )
        if any(
            value is not None and not self._is_finite_timestamp(value)
            for value in optional_timestamps
        ):
            return None
        if continuous_sit_start is not None and continuous_sit_start > saved_at:
            return None
        if last_presence_time is not None and last_presence_time > saved_at:
            return None

        mode = "focus" if trusted_status == self.PRESENT else "away"
        if active_timer is not None and active_timer != mode:
            return None
        if observation_status != self.UNKNOWN and observation_status != trusted_status:
            return None
        if observation_status == self.UNKNOWN and active_timer is not None:
            return None

        if mode == "focus":
            if not (
                continuous_sit_start is not None
                and last_presence_time is not None
                and continuous_sit_start <= last_presence_time <= trusted_time
                and focus_elapsed <= saved_at - continuous_sit_start
                and away_elapsed == 0
                and away_start_time is None
                and last_missing_time is None
            ):
                return None
        else:
            if not (
                away_start_time is not None
                and last_missing_time == away_start_time
                and away_start_time <= trusted_time
                and away_elapsed <= saved_at - away_start_time
            ):
                return None
            if continuous_sit_start is None:
                if focus_elapsed != 0 or last_presence_time is not None:
                    return None
            elif not (
                focus_elapsed <= saved_at - continuous_sit_start
                and last_presence_time is not None
                and continuous_sit_start <= last_presence_time <= away_start_time
                and away_elapsed < self.grace_period
            ):
                return None

        return {
            "mode": mode,
            "loaded_at": float(loaded_at),
            "saved_at": float(saved_at),
            "continuous_sit_start": (
                float(continuous_sit_start)
                if continuous_sit_start is not None
                else None
            ),
            "focus_elapsed_seconds": float(focus_elapsed),
            "away_elapsed_seconds": float(away_elapsed),
            "away_start_time": (
                float(away_start_time) if away_start_time is not None else None
            ),
            "last_presence_time": (
                float(last_presence_time)
                if last_presence_time is not None
                else None
            ),
            "last_missing_time": (
                float(last_missing_time) if last_missing_time is not None else None
            ),
            "last_trusted_observation_status": trusted_status,
            "last_trusted_observation_time": float(trusted_time),
            "last_observation_status": observation_status,
            "last_observation_time": float(observation_time),
        }

    def _persist_presence_state(
        self,
        *,
        saved_at=None,
        observation_status=None,
        observation_time=None,
    ):
        if self.state_path is None:
            return

        has_activity = (
            self.continuous_sit_start is not None
            or self.away_start_time is not None
            or self.focus_elapsed_seconds > 0
            or self.away_elapsed_seconds > 0
            or self.active_timer is not None
        )
        if not has_activity:
            return

        if saved_at is None:
            saved_at = self.last_observation_time
        if observation_status is None:
            observation_status = self.last_observation_status
        if observation_time is None:
            observation_time = self.last_observation_time
        if not (
            self._is_finite_timestamp(saved_at)
            and observation_status in {self.PRESENT, self.ABSENT, self.UNKNOWN}
            and self._is_finite_timestamp(observation_time)
        ):
            return

        temp_path = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": self.PRESENCE_STATE_VERSION,
                "saved_at": saved_at,
                "continuous_sit_start": self.continuous_sit_start,
                "focus_elapsed_seconds": self.focus_elapsed_seconds,
                "away_elapsed_seconds": self.away_elapsed_seconds,
                "away_start_time": self.away_start_time,
                "active_timer": self.active_timer,
                "active_segment_started_at": self.active_segment_started_at,
                "last_presence_time": self.last_presence_time,
                "last_missing_time": self.last_missing_time,
                "last_trusted_observation_status": (
                    self.last_trusted_observation_status
                ),
                "last_trusted_observation_time": self.last_trusted_observation_time,
                "last_observation_status": observation_status,
                "last_observation_time": observation_time,
            }
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                dir=self.state_path.parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
                json.dump(payload, state_file)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temp_path, self.state_path)
            temp_path = None
        except Exception as exc:
            print(f"Focus presence state write error: {exc}", file=sys.stderr)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _restore_recovery_candidate_locked(self, status, observed_at):
        candidate = self._recovery_candidate
        if candidate is None or status == self.UNKNOWN:
            return False

        self._recovery_candidate = None
        expected_status = (
            self.PRESENT if candidate["mode"] == "focus" else self.ABSENT
        )
        valid = (
            status == expected_status
            and candidate["loaded_at"] <= observed_at
            and 0 <= observed_at - candidate["saved_at"] < self.grace_period
        )
        if not valid:
            self._remove_presence_state()
            return False

        self.continuous_sit_start = candidate["continuous_sit_start"]
        self.focus_elapsed_seconds = candidate["focus_elapsed_seconds"]
        self.away_elapsed_seconds = candidate["away_elapsed_seconds"]
        self.away_start_time = candidate["away_start_time"]
        self.last_presence_time = candidate["last_presence_time"]
        self.last_missing_time = candidate["last_missing_time"]
        self.last_trusted_observation_status = candidate[
            "last_trusted_observation_status"
        ]
        self.last_trusted_observation_time = candidate[
            "last_trusted_observation_time"
        ]
        if self.last_observation_time is None:
            self.last_observation_status = candidate["last_observation_status"]
            self.last_observation_time = candidate["last_observation_time"]
        self.active_timer = None
        self.active_segment_started_at = None
        return True

    @staticmethod
    def _optional_timestamp_is_valid(value, now):
        return value is None or (
            Monitor._is_finite_timestamp(value) and value <= now
        )

    def _runtime_state_is_valid_locked(self, now):
        if not (
            self._is_finite_timestamp(self.focus_elapsed_seconds)
            and self._is_finite_timestamp(self.away_elapsed_seconds)
            and self._optional_timestamp_is_valid(
                self.continuous_sit_start, now
            )
            and self._optional_timestamp_is_valid(self.away_start_time, now)
            and self._optional_timestamp_is_valid(
                self.active_segment_started_at, now
            )
            and self._optional_timestamp_is_valid(self.last_presence_time, now)
            and self._optional_timestamp_is_valid(self.last_missing_time, now)
            and self._optional_timestamp_is_valid(
                self.last_trusted_observation_time, now
            )
            and self._optional_timestamp_is_valid(self.last_observation_time, now)
            and self._optional_timestamp_is_valid(
                self.last_notification_time, now
            )
            and self.active_timer in {"focus", "away", None}
        ):
            return False

        if self.active_timer is None:
            if self.active_segment_started_at is not None:
                return False
        elif self.active_segment_started_at is None:
            return False

        trusted_status = self.last_trusted_observation_status
        trusted_time = self.last_trusted_observation_time
        observation_status = self.last_observation_status
        observation_time = self.last_observation_time
        if (trusted_status is None) != (trusted_time is None):
            return False
        if trusted_status not in {self.PRESENT, self.ABSENT, None}:
            return False
        if (observation_status is None) != (observation_time is None):
            return False
        if observation_status not in {
            self.PRESENT,
            self.ABSENT,
            self.UNKNOWN,
            None,
        }:
            return False
        if trusted_time is not None and (
            observation_time is None or trusted_time > observation_time
        ):
            return False
        if observation_status not in {None, self.UNKNOWN, trusted_status}:
            return False
        if observation_status == self.UNKNOWN and self.active_timer is not None:
            return False
        if self.active_timer is not None and (
            observation_time is None
            or self.active_segment_started_at < observation_time
        ):
            return False

        if trusted_status is None:
            return (
                self.continuous_sit_start is None
                and self.focus_elapsed_seconds == 0
                and self.away_elapsed_seconds == 0
                and self.away_start_time is None
                and self.active_timer is None
                and self.last_presence_time is None
                and self.last_missing_time is None
            )

        if trusted_status == self.PRESENT:
            return (
                self.continuous_sit_start is not None
                and self.last_presence_time is not None
                and self.continuous_sit_start <= self.last_presence_time <= trusted_time
                and self.focus_elapsed_seconds
                <= now - self.continuous_sit_start
                and self.away_elapsed_seconds == 0
                and self.away_start_time is None
                and self.last_missing_time is None
                and self.active_timer in {"focus", None}
            )

        if not (
            self.away_start_time is not None
            and self.last_missing_time == self.away_start_time
            and self.away_start_time <= trusted_time
            and self.away_elapsed_seconds <= now - self.away_start_time
            and self.active_timer in {"away", None}
        ):
            return False
        if self.continuous_sit_start is None:
            return self.focus_elapsed_seconds == 0 and self.last_presence_time is None
        return (
            self.last_presence_time is not None
            and self.continuous_sit_start
            <= self.last_presence_time
            <= self.away_start_time
            and self.focus_elapsed_seconds <= now - self.continuous_sit_start
            and self.away_elapsed_seconds < self.grace_period
        )

    def _pause_active_timer_locked(self, paused_at):
        if self.active_timer is None:
            return
        safe_pause = max(paused_at, self.active_segment_started_at)
        self._settle_active_segment_locked(safe_pause)
        self._enforce_away_grace_locked()
        self._persist_presence_state(saved_at=safe_pause)

    def _public_active_timer_locked(self):
        if self.active_timer in {"focus", "away"}:
            return self.active_timer
        if (
            self.last_trusted_observation_status == self.PRESENT
            and self.continuous_sit_start is not None
        ):
            return "focus"
        if (
            self.last_trusted_observation_status == self.ABSENT
            and self.away_start_time is not None
        ):
            return "away"
        return "none"

    def get_sedentary_snapshot(self, *, now=None):
        snapshot_time = time.time() if now is None else now
        with self._state_lock:
            if not self._is_finite_timestamp(snapshot_time):
                self._reset_sedentary_state_locked()
                return {
                    "detection_status": "unknown",
                    "has_focus_session": False,
                    "focus_duration_seconds": 0.0,
                    "away_duration_seconds": 0.0,
                    "active_timer": "none",
                    "sedentary_threshold": self.sedentary_threshold,
                }

            if not self._runtime_state_is_valid_locked(snapshot_time):
                self._reset_sedentary_state_locked()
                return {
                    "detection_status": "unknown",
                    "has_focus_session": False,
                    "focus_duration_seconds": 0.0,
                    "away_duration_seconds": 0.0,
                    "active_timer": "none",
                    "sedentary_threshold": self.sedentary_threshold,
                }

            heartbeat = self.last_monitor_heartbeat
            stale_timeout = self.monitor_stale_timeout
            heartbeat_is_valid = (
                self._is_finite_timestamp(heartbeat)
                and heartbeat <= snapshot_time
            )
            stale_timeout_is_valid = self._is_finite_timestamp(stale_timeout)
            observation_is_current = (
                heartbeat_is_valid
                and self.last_observation_time is not None
                and heartbeat <= self.last_observation_time <= snapshot_time
            )
            heartbeat_is_stale = (
                heartbeat_is_valid
                and stale_timeout_is_valid
                and snapshot_time - heartbeat >= stale_timeout
            )

            if not heartbeat_is_valid or not stale_timeout_is_valid:
                detection_status = "unknown"
                if self.active_timer is not None:
                    safe_boundary = max(
                        self.active_segment_started_at,
                        self.last_observation_time,
                    )
                    self._pause_active_timer_locked(safe_boundary)
            elif heartbeat_is_stale:
                detection_status = "stale"
                stale_boundaries = [heartbeat + stale_timeout]
                if self.last_observation_time is not None:
                    stale_boundaries.append(self.last_observation_time)
                stale_cutoff = min(
                    snapshot_time,
                    max(stale_boundaries),
                )
                self._pause_active_timer_locked(stale_cutoff)
            elif not observation_is_current:
                detection_status = "unknown"
                if self.active_timer is not None:
                    self._pause_active_timer_locked(heartbeat)
            elif self.last_observation_status in {
                self.PRESENT,
                self.ABSENT,
                self.UNKNOWN,
            }:
                detection_status = self.last_observation_status.lower()
            else:
                detection_status = "unknown"

            if (
                detection_status == "absent"
                and self.active_timer == "away"
                and self.continuous_sit_start is not None
            ):
                projected_away = self.away_elapsed_seconds + (
                    snapshot_time - self.active_segment_started_at
                )
                if projected_away >= self.grace_period:
                    self._settle_active_segment_locked(snapshot_time)
                    self._enforce_away_grace_locked()
                    self._start_active_timer_locked("away", snapshot_time)
                    self._persist_presence_state(saved_at=snapshot_time)

            focus_duration = self.focus_elapsed_seconds
            away_duration = self.away_elapsed_seconds
            if detection_status == "present" and self.active_timer == "focus":
                focus_duration += snapshot_time - self.active_segment_started_at
            elif detection_status == "absent" and self.active_timer == "away":
                away_duration += snapshot_time - self.active_segment_started_at

            return {
                "detection_status": detection_status,
                "has_focus_session": self.continuous_sit_start is not None,
                "focus_duration_seconds": focus_duration,
                "away_duration_seconds": away_duration,
                "active_timer": self._public_active_timer_locked(),
                "sedentary_threshold": self.sedentary_threshold,
            }

    def record_presence_observation(self, observation, *, observed_at=None):
        current_time = time.time() if observed_at is None else observed_at
        if observation is True:
            status = self.PRESENT
        elif observation is False:
            status = self.ABSENT
        elif observation is None:
            status = self.UNKNOWN
        else:
            raise ValueError("presence observation must be True, False, or None")

        with self._state_lock:
            if not self._is_finite_timestamp(current_time):
                self._reset_sedentary_state_locked()
                return self.UNKNOWN

            if (
                self._recovery_candidate is not None
                and current_time < self._recovery_candidate["loaded_at"]
            ):
                self._recovery_candidate = None
                self._remove_presence_state()
            elif self._recovery_candidate is not None and status != self.UNKNOWN:
                self._restore_recovery_candidate_locked(status, current_time)

            clock_rolled_back = (
                self.last_observation_time is not None
                and current_time < self.last_observation_time
            )
            if clock_rolled_back:
                self._reset_sedentary_state_locked()
            elif not self._runtime_state_is_valid_locked(current_time):
                self._reset_sedentary_state_locked()

            self._settle_active_segment_locked(current_time)
            self._enforce_away_grace_locked()

            if status == self.PRESENT:
                if (
                    self.continuous_sit_start is None
                    or self.continuous_sit_start > current_time
                ):
                    self.continuous_sit_start = current_time
                self.away_elapsed_seconds = 0.0
                self.away_start_time = None
                self.last_missing_time = None
                self.last_presence_time = current_time
                self.last_trusted_observation_status = self.PRESENT
                self.last_trusted_observation_time = current_time
                self._start_active_timer_locked("focus", current_time)
            elif status == self.UNKNOWN:
                # Unknown time is deliberately excluded from both accumulators.
                pass
            else:
                if self.away_start_time is None:
                    self.away_start_time = current_time
                self.last_missing_time = self.away_start_time
                self.last_trusted_observation_status = self.ABSENT
                self.last_trusted_observation_time = current_time
                self._start_active_timer_locked("away", current_time)
                self._enforce_away_grace_locked()

            self.last_observation_status = status
            self._persist_presence_state(
                saved_at=current_time,
                observation_status=status,
                observation_time=current_time,
            )
            self.last_observation_time = current_time
            return status

    def run_task(
        self,
        pre_captured_frame=_PRE_CAPTURED_FRAME_UNSET,
        *,
        observation_validator=None,
    ):
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")

        cycle_started_at = time.time()
        with self._state_lock:
            if self.last_monitor_heartbeat is not None:
                monitor_gap = cycle_started_at - self.last_monitor_heartbeat
                if monitor_gap >= self.monitor_stale_timeout:
                    stale_cutoff = self.last_monitor_heartbeat + self.monitor_stale_timeout
                    self._pause_for_stale_gap_locked(stale_cutoff)
                    print(
                        f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"Monitor gap {int(monitor_gap)}s exceeded timeout. Pausing timers."
                    )
            if self.active_timer is not None:
                self._pause_active_timer_locked(cycle_started_at)
            self.last_monitor_heartbeat = cycle_started_at
        observation_recorded = False
        observation_status = self.UNKNOWN

        try:
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Getting location")
            latitude, longitude = get_location()
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_photo()")
            if pre_captured_frame is _PRE_CAPTURED_FRAME_UNSET:
                real_person, photo_path = take_photo(
                    self.camera,
                    latitude,
                    longitude,
                    self.photos_path,
                )
            else:
                real_person, photo_path = take_photo(
                    self.camera,
                    latitude,
                    longitude,
                    self.photos_path,
                    pre_captured_frame=pre_captured_frame,
                )

            if observation_validator is not None:
                try:
                    observation_is_valid = observation_validator() is True
                except Exception as validation_error:
                    print(
                        f"Presence observation validation error: {validation_error}",
                        file=sys.stderr,
                    )
                    observation_is_valid = False
                if not observation_is_valid:
                    real_person = None

            current_time = time.time()
            had_active_session = self.continuous_sit_start is not None
            observation_status = self.record_presence_observation(
                real_person,
                observed_at=current_time,
            )
            observation_recorded = True

            if observation_status == self.PRESENT:
                sit_duration = self.focus_elapsed_seconds
                if sit_duration >= self.sedentary_threshold:
                    if self.last_notification_time is None or (
                        current_time - self.last_notification_time
                    ) >= self.notification_interval:
                        threading.Thread(
                            target=self.send_sedentary_notification,
                            args=(int(sit_duration // 60),),
                            daemon=True,
                        ).start()
                        self.last_notification_time = current_time

                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_and_save_screenshots()")
                screenshot_path = take_and_save_screenshots(latitude, longitude, self.screenshots_path)

                if photo_path:
                    self.paths["photo"] = photo_path
                if screenshot_path:
                    self.paths["screenshot"] = screenshot_path
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Done. (Sedentary: {int(sit_duration / 60)} mins)")
            elif observation_status == self.ABSENT:
                if had_active_session and self.continuous_sit_start is None:
                    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} User left for >2mins. Resetting sedentary timer.")
                elif self.last_missing_time is not None:
                    missing_duration = self.away_elapsed_seconds
                    if missing_duration >= self.grace_period:
                        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} User left for >2mins. Resetting sedentary timer.")
                    else:
                        print(
                            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                            f"No person detected. (Grace period: {int(self.grace_period - missing_duration)}s left)",
                            file=sys.stderr,
                        )
            else:
                print(
                    f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                    "Presence unavailable. Preserving sedentary timer.",
                    file=sys.stderr,
                )

        except Exception as e:
            print(f"Task error: {e}", file=sys.stderr)
            if not observation_recorded:
                try:
                    self.record_presence_observation(
                        None,
                        observed_at=cycle_started_at,
                    )
                except Exception as observation_error:
                    print(
                        f"Presence observation error: {observation_error}",
                        file=sys.stderr,
                    )

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")
        return observation_status

    def send_sedentary_notification(self, minutes):
        print(f"Sending sedentary notification for {minutes} minutes of continuous sitting.")
        try:
            message = f"你已经连续工作了 {minutes} 分钟了！请起立活动一下，走动走动喝口水，防止病痛、保护视力。"
            title = "AI 健康管家 (久坐提醒)"
            if sys.platform == "darwin":
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f"display notification {json.dumps(message, ensure_ascii=False)} "
                        f"with title {json.dumps(title, ensure_ascii=False)}",
                    ],
                    check=False,
                )
                return

            if sys.platform != "win32":
                subprocess.run(["notify-send", title, message], check=False)
                return

            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Warning
            $notify.BalloonTipIcon = 'Warning'
            $notify.BalloonTipTitle = '{title}'
            $notify.BalloonTipText = '{message}'
            $notify.Visible = $True
            $notify.ShowBalloonTip(10000)
            Start-Sleep -Seconds 10
            $notify.Dispose()
            """
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], startupinfo=startupinfo)
        except Exception as e:
            print(f"Notification error: {e}")
