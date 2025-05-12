
import piexif
import asyncio
# winrt最高支持到Python 3.9，Python 3.10及以上得使用winsdk，而且不会报com错误
# from winrt.windows.devices.geolocation import Geolocator
from winsdk.windows.devices.geolocation import Geolocator
from datetime import datetime
import cv2
import threading
import platform


# 同步获取经纬度
def get_location():
    # 台式机就固定一个经纬度
    if platform.node() == "Biao_PC":
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 台式机为固定位置，只需要指定经纬度即可")
        latitude = 22.348769382455153
        longitude = 113.58774933243512
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Location: {latitude}, {longitude}")
        return latitude, longitude
    else:
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 非指定台式机，需要调用定位服务获取定位信息")

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
