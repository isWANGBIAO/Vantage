# 该代码用于从摄像头捕获照片，并将其保存到指定的文件夹中。同时，将照片的信息（包括时间戳和路径）更新到一个JSON格式的知识库文件中。

import threading
import cv2
import os
import json
from datetime import datetime
import time
from .get_best_photo import capture_best_photo
import cv2
import piexif
import asyncio
from winrt.windows.devices.geolocation import Geolocator
import sys


def set_max_camera_resolution(cam):
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


# 同步获取经纬度


def get_location():
    time.sleep(1)  # 确保定位服务已启动

    async def fetch_location():
        try:
            locator = Geolocator()
            position = await locator.get_geoposition_async()
            latitude = position.coordinate.point.position.latitude
            longitude = position.coordinate.point.position.longitude
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Location: {latitude}, {longitude}")
            return latitude, longitude
        except Exception as e:
            print(f"⚠️ 获取定位信息失败：{e}")
            return None, None

    def run_async_in_thread(result_holder):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        latitude, longitude = loop.run_until_complete(fetch_location())
        result_holder['latitude'] = latitude
        result_holder['longitude'] = longitude

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():  # 如果事件循环已在运行（如在 GUI 程序中）
            result_holder = {}
            thread = threading.Thread(target=run_async_in_thread, args=(result_holder,))
            thread.start()
            thread.join()  # 等待子线程完成
            latitude = result_holder.get('latitude')
            longitude = result_holder.get('longitude')
        else:
            latitude, longitude = loop.run_until_complete(fetch_location())
    except RuntimeError:  # 如果没有事件循环
        latitude, longitude = asyncio.run(fetch_location())

    time.sleep(1)
    return latitude, longitude


# 将十进制度数转换为EXIF格式 (度, 分, 秒)
def convert_to_exif_coords(value):
    deg = int(value)
    min_float = abs((value - deg) * 60)
    min = int(min_float)
    sec = int((min_float - min) * 6000)
    return ((deg, 1), (min, 1), (sec, 100))


# 保存图片并写入EXIF GPS信息
def save_image_with_gps(photo_path, frame, latitude, longitude):
    # 保存图像
    cv2.imwrite(photo_path, frame)

    # 准备GPS EXIF数据
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: 'N' if latitude >= 0 else 'S',
        piexif.GPSIFD.GPSLatitude: convert_to_exif_coords(abs(latitude)),
        piexif.GPSIFD.GPSLongitudeRef: 'E' if longitude >= 0 else 'W',
        piexif.GPSIFD.GPSLongitude: convert_to_exif_coords(abs(longitude)),
    }

    # 写入EXIF信息
    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, photo_path)


def take_photo():
    # TODO: 如无需要，勿增实体。等到这里成为性能瓶颈再优化代码，提高拍照的效率,使得每次拍照尽量清晰以及对齐时间间隔
    # 打开摄像头
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Opening camera")

    cam = cv2.VideoCapture(0)

    # 检查摄像头是否成功打开
    if not cam.isOpened():
        print('Failed to open camera.', file=sys.stderr)
        return

    # 自动调整到摄像头最高的清晰度
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution")
    set_max_camera_resolution(cam)

    # 获取经纬度信息
    latitude, longitude = get_location()

    # 获取最清晰的一帧图像
    best_frame = capture_best_photo(cam)

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
