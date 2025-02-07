# 该代码用于从摄像头捕获照片，并将其保存到指定的文件夹中。同时，将照片的信息（包括时间戳和路径）更新到一个JSON格式的知识库文件中。

import threading
import cv2
import os
import json
from datetime import datetime
import time
from .get_best_photo import capture_best_photo
import cv2
import sys
import subprocess
from ..get_location import save_image_with_gps


def get_system_model():
    try:
        output = subprocess.check_output('wmic csproduct get name', shell=True)
        return output.decode().split('\n')[1].strip()
    except:
        return "未知电脑型号"


def set_max_camera_resolution(cam):
    # 获取电脑型号
    system_model = get_system_model()
    if system_model == "MRGF-XX":
        return (1280, 720)  # MRGF-XX笔记本摄像头最大分辨率
    # 常见分辨率列表，从高到低排列
    resolutions = [
        # (7680, 4320),  # 8K UHD
        # (5120, 2880),  # 5K
        (3840, 2160),  # 4K UHD
        (1280, 720),   # 720p
        (2560, 1600),  # WQXGA
        (2560, 1440),  # QHD
        (2048, 1080),  # 2K
        (1920, 1200),  # WUXGA
        (1920, 1080),  # 1080p
        (1600, 900),   # HD+
        (1440, 900),   # WXGA+
        (1366, 768),   # FWXGA
        (1280, 800),   # WXGA
        (1280, 720),   # 720p
        (1024, 768),   # XGA
        (800, 600),    # SVGA
        (640, 480),    # VGA
        (320, 240)     # QVGA
    ]

    # 从高到低尝试设置最大支持分辨率
    for width, height in resolutions:
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual_width = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if actual_width == width and actual_height == height:
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Camera resolution set to {width} x {height}")

            return (width, height)
    # 如果无法匹配到任何分辨率，使用默认分辨率
    default_width = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
    default_height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Using default camera resolution {default_width}x{default_height}")
    return (default_width, default_height)


def take_photo(latitude, longitude):
    # TODO: 如无需要，勿增实体。等到这里成为性能瓶颈再优化代码，提高拍照的效率,使得每次拍照尽量清晰以及对齐时间间隔

    # 打开摄像头
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Opening camera")
    cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # 强制使用 DirectShow 更底层更快速

    # 检查摄像头是否成功打开
    if not cam.isOpened():
        print('Failed to open camera.', file=sys.stderr)
        return

    # 自动调整到摄像头最高的清晰度
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution")
    set_max_camera_resolution(cam)

    # 获取最清晰的一帧图像
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Taking photo")
    best_frame = capture_best_photo(cam)

    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Saving photo")
    # 检查是否成功获取最佳图像
    if best_frame is not None:
        # 生成当前时间的时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 构建照片文件名
        photo_name = f'photo_{timestamp}.jpg'

        # 按照年月日创建四级文件夹，然后把当天的照片放到当天的文件夹的下面
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        day = now.strftime('%d')
        hour = now.strftime('%H')
        daily_folder = os.path.join('.', 'logs', 'photos', year, month, day, hour)
        if not os.path.exists(daily_folder):
            os.makedirs(daily_folder)
        photo_path = os.path.join(daily_folder, photo_name)

        # 保存捕获的图像到指定路径
        save_image_with_gps(photo_path, best_frame, latitude, longitude)

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Photo taken and saved as {photo_path}")
    else:
        # 如果未能捕获清晰图像，打印错误信息
        print('Failed to capture a clear image.', file=sys.stderr)

    # 释放摄像头资源
    cam.release()
