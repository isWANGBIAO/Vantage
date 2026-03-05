import os
from datetime import datetime
import mss
import sys
from ..get_location import save_image_with_gps
import numpy as np
import cv2


def take_and_save_screenshots(latitude, longitude, screenshots_path):
    try:
        with mss.mss() as sct:
            monitors = sct.monitors  # 获取所有监视器的信息
            screenshots = []  # 用于存储所有屏幕截图

            # 截取所有屏幕并存储到内存
            for i, monitor in enumerate(monitors[1:], start=1):  # 跳过 monitors[0]（虚拟全屏）
                screenshot = sct.grab(monitor)
                # 将 raw 数据转换为 numpy 数组（BGR 格式，适合 OpenCV）
                img = np.array(screenshot)
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)  # 去掉 alpha 通道，转换为 BGR 格式
                screenshots.append((i, img))  # 存储屏幕编号和图像对象

            # 生成当前时间的时间戳
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # 按年月日小时创建四级文件夹
            now = datetime.now()
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            hour = now.strftime('%H')
            daily_folder = os.path.join(screenshots_path, year, month, day, hour)
            os.makedirs(daily_folder, exist_ok=True)

            # 保存所有截图
            screenshot_path = None
            for i, img in screenshots:
                screenshot_name = f'screenshot_{timestamp}_monitor_{i}.jpg'
                screenshot_path = os.path.join(daily_folder, screenshot_name)

                # 保存捕获的图像到指定路径
                save_image_with_gps(screenshot_path, img, latitude, longitude)

                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Screenshot for monitor {i} saved as {screenshot_path}")
            return screenshot_path
    except Exception as e:
        print(f'Failed to capture and save the screens: {e}', file=sys.stderr)


if __name__ == '__main__':
    # When running directly, use some test parameters or default ones.
    # We use some dummy location coordinates and a test output directory.
    test_lat, test_lon = 0.0, 0.0
    test_dir = os.path.join(os.path.expanduser('~'), 'Desktop', 'screenshots_test')
    take_and_save_screenshots(test_lat, test_lon, test_dir)
