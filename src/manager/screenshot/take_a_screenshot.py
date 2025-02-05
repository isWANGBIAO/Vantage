import os
from datetime import datetime
import mss
from PIL import Image


def take_and_save_screenshots():
    try:
        with mss.mss() as sct:
            monitors = sct.monitors  # 获取所有监视器的信息
            screenshots = []  # 用于存储所有屏幕截图

            # 截取所有屏幕并存储到内存
            for i, monitor in enumerate(monitors[1:], start=1):  # 跳过 monitors[0]（虚拟全屏）
                screenshot = sct.grab(monitor)
                img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
                screenshots.append((i, img))  # 存储屏幕编号和图像对象

            # 生成当前时间的时间戳
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # 按年月日小时创建四级文件夹
            now = datetime.now()
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            hour = now.strftime('%H')
            daily_folder = os.path.join('./logs/screenshots', year, month, day, hour)
            os.makedirs(daily_folder, exist_ok=True)

            # 保存所有截图
            for i, img in screenshots:
                screenshot_name = f'screenshot_{timestamp}_monitor_{i}.png'
                screenshot_path = os.path.join(daily_folder, screenshot_name)
                img.save(screenshot_path)
                # print(f'Screenshot for monitor {i} saved as {screenshot_path}')

    except Exception as e:
        print(f'Failed to capture and save the screens: {e}')


if __name__ == '__main__':
    take_and_save_screenshots()
