import os
from datetime import datetime
import mss
import sys
import subprocess
import tempfile
from ..get_location import save_image_with_gps
import numpy as np
import cv2


def _ordered_physical_monitors(monitors):
    physical_monitors = list(monitors[1:])
    for index, monitor in enumerate(physical_monitors):
        if (
            monitor["left"] <= 0 < monitor["left"] + monitor["width"]
            and monitor["top"] <= 0 < monitor["top"] + monitor["height"]
        ):
            return [monitor, *physical_monitors[:index], *physical_monitors[index + 1:]]
    return physical_monitors


def _build_screenshot_folder(screenshots_path):
    now = datetime.now()
    daily_folder = os.path.join(
        screenshots_path,
        now.strftime('%Y'),
        now.strftime('%m'),
        now.strftime('%d'),
        now.strftime('%H'),
    )
    os.makedirs(daily_folder, exist_ok=True)
    return daily_folder


def _save_macos_screencapture(latitude, longitude, daily_folder, timestamp):
    if sys.platform != "darwin":
        return None

    screenshot_path = os.path.join(daily_folder, f'screenshot_{timestamp}_monitor_1.jpg')
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", dir=daily_folder, delete=False) as temp_file:
            temp_path = temp_file.name

        subprocess.run(["screencapture", "-x", temp_path], check=True)
        img = cv2.imread(temp_path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("macOS screencapture returned an unreadable image")

        save_image_with_gps(screenshot_path, img, latitude, longitude)
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Screenshot for monitor 1 saved as {screenshot_path}")
        return screenshot_path
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def take_and_save_screenshots(latitude, longitude, screenshots_path):
    try:
        with mss.mss() as sct:
            monitors = _ordered_physical_monitors(sct.monitors)
            screenshots = []  # 用于存储所有屏幕截图

            # 截取所有屏幕并存储到内存
            for i, monitor in enumerate(monitors, start=1):
                screenshot = sct.grab(monitor)
                # 将 raw 数据转换为 numpy 数组（BGR 格式，适合 OpenCV）
                img = np.array(screenshot)
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)  # 去掉 alpha 通道，转换为 BGR 格式
                screenshots.append((i, img))  # 存储屏幕编号和图像对象

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            daily_folder = _build_screenshot_folder(screenshots_path)

            if not screenshots:
                fallback_path = _save_macos_screencapture(latitude, longitude, daily_folder, timestamp)
                if fallback_path:
                    return fallback_path
                print("No displays available for screenshot capture", file=sys.stderr)
                return None

            # 保存所有截图
            screenshot_paths = []
            for i, img in screenshots:
                screenshot_name = f'screenshot_{timestamp}_monitor_{i}.jpg'
                screenshot_path = os.path.join(daily_folder, screenshot_name)

                # 保存捕获的图像到指定路径
                save_image_with_gps(screenshot_path, img, latitude, longitude)
                screenshot_paths.append(screenshot_path)

                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Screenshot for monitor {i} saved as {screenshot_path}")
            return screenshot_paths[0]
    except Exception as e:
        print(f'Failed to capture and save the screens: {e}', file=sys.stderr)


if __name__ == '__main__':
    # When running directly, use some test parameters or default ones.
    # We use some dummy location coordinates and a test output directory.
    test_lat, test_lon = 0.0, 0.0
    test_dir = os.path.join(os.path.expanduser('~'), 'Desktop', 'screenshots_test')
    take_and_save_screenshots(test_lat, test_lon, test_dir)
