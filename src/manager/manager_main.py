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
    PRESENCE_STATE_VERSION = 1
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

        self.continuous_sit_start = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.last_presence_time = None
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
        self.continuous_sit_start = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.last_presence_time = None
        self._recovery_candidate = None
        self._remove_presence_state()

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
            continuous_sit_start = payload.get("continuous_sit_start")
            last_presence_time = payload.get("last_presence_time")
            loaded_at = time.time()

            valid = (
                payload.get("version") == self.PRESENCE_STATE_VERSION
                and self._is_finite_timestamp(continuous_sit_start)
                and self._is_finite_timestamp(last_presence_time)
                and continuous_sit_start <= last_presence_time <= loaded_at
                and 0 <= loaded_at - last_presence_time < self.grace_period
            )
            if not valid:
                raise ValueError("invalid or stale focus presence state")

            self._recovery_candidate = (
                float(continuous_sit_start),
                float(last_presence_time),
                loaded_at,
            )
        except Exception as exc:
            self._recovery_candidate = None
            print(f"Focus presence state load error: {exc}", file=sys.stderr)
            self._remove_presence_state()

    def _persist_presence_state(self):
        if (
            self.state_path is None
            or self.continuous_sit_start is None
            or self.last_presence_time is None
        ):
            return

        temp_path = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": self.PRESENCE_STATE_VERSION,
                "continuous_sit_start": self.continuous_sit_start,
                "last_presence_time": self.last_presence_time,
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

    def _start_or_restore_session(self, observed_at):
        candidate = self._recovery_candidate
        self._recovery_candidate = None
        if candidate is not None:
            prior_start, prior_last_presence, candidate_loaded_at = candidate
            recovery_gap = observed_at - prior_last_presence
            if (
                self._is_finite_timestamp(observed_at)
                and prior_start <= prior_last_presence <= candidate_loaded_at <= observed_at
                and 0 <= recovery_gap < self.grace_period
            ):
                self.continuous_sit_start = prior_start
                return

        self.continuous_sit_start = observed_at

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

        if (
            self._recovery_candidate is not None
            and current_time < self._recovery_candidate[2]
        ):
            self._recovery_candidate = None
            self._remove_presence_state()

        clock_rolled_back = (
            self.last_observation_time is not None
            and current_time < self.last_observation_time
        )
        if clock_rolled_back:
            self.reset_sedentary_state()

        if status == self.PRESENT:
            self.last_missing_time = None
            if (
                self.continuous_sit_start is None
                or self.continuous_sit_start > current_time
            ):
                self._start_or_restore_session(current_time)
            self.last_presence_time = current_time
            self._persist_presence_state()
        elif status == self.UNKNOWN:
            # An unavailable measurement cannot count toward confirmed absence.
            self.last_missing_time = None
        else:
            if self.last_missing_time is None or current_time < self.last_missing_time:
                self.last_missing_time = current_time
            elif current_time - self.last_missing_time >= self.grace_period:
                self.reset_sedentary_state()

        self.last_observation_status = status
        self.last_observation_time = current_time
        return status

    def run_task(self, pre_captured_frame=_PRE_CAPTURED_FRAME_UNSET):
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")

        cycle_started_at = time.time()
        if self.last_monitor_heartbeat is not None:
            monitor_gap = cycle_started_at - self.last_monitor_heartbeat
            if monitor_gap >= self.monitor_stale_timeout:
                if self.continuous_sit_start is not None:
                    print(
                        f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"Monitor gap {int(monitor_gap)}s exceeded timeout. Resetting sedentary timer."
                    )
                self.reset_sedentary_state()
        self.last_monitor_heartbeat = cycle_started_at
        observation_recorded = False

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

            current_time = time.time()
            had_active_session = self.continuous_sit_start is not None
            observation_status = self.record_presence_observation(
                real_person,
                observed_at=current_time,
            )
            observation_recorded = True

            if observation_status == self.PRESENT:
                sit_duration = current_time - self.continuous_sit_start
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
                    missing_duration = current_time - self.last_missing_time
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
