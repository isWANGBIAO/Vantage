from .take_photo.take_a_photo import take_photo
from .screenshot.take_a_screenshot import take_and_save_screenshots
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from .get_location import get_location


class Monitor:
    def __init__(self, camera, paths, photos_path, screenshots_path):
        self.camera = camera
        self.paths = paths
        self.photos_path = photos_path
        self.screenshots_path = screenshots_path

        base_dir = self.photos_path
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BASE_DIR: {base_dir}")
        knowledge_base = os.path.join(base_dir, "knowledge_base.json")
        if not os.path.exists(knowledge_base):
            with open(knowledge_base, "w") as f:
                json.dump({}, f)

        self.continuous_sit_start = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.sedentary_threshold = 20 * 60
        self.notification_interval = 5 * 60
        self.grace_period = 2 * 60
        self.last_monitor_heartbeat = None
        self.monitor_stale_timeout = self.grace_period

    def reset_sedentary_state(self):
        self.continuous_sit_start = None
        self.last_missing_time = None
        self.last_notification_time = None

    def run_task(self):
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

        try:
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Getting location")
            latitude, longitude = get_location()
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_photo()")
            real_person, photo_path = take_photo(self.camera, latitude, longitude, self.photos_path)

            current_time = time.time()

            if real_person:
                self.last_missing_time = None

                if self.continuous_sit_start is None:
                    self.continuous_sit_start = current_time

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

                self.paths["photo"] = photo_path
                self.paths["screenshot"] = screenshot_path
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Done. (Sedentary: {int(sit_duration / 60)} mins)")
            else:
                if self.last_missing_time is None:
                    self.last_missing_time = current_time

                missing_duration = current_time - self.last_missing_time
                if missing_duration >= self.grace_period:
                    if self.continuous_sit_start is not None:
                        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} User left for >2mins. Resetting sedentary timer.")
                    self.reset_sedentary_state()
                else:
                    print(
                        f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"No person detected. (Grace period: {int(self.grace_period - missing_duration)}s left)",
                        file=sys.stderr,
                    )

        except Exception as e:
            print(f"Task error: {e}", file=sys.stderr)

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
