import asyncio
import os
import sys
import threading
from datetime import datetime

import cv2
import piexif

if sys.platform == "win32":
    try:
        from winsdk.windows.devices.geolocation import Geolocator
    except ImportError:
        Geolocator = None
else:
    Geolocator = None


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _configured_static_location():
    latitude = os.environ.get("VANTAGE_STATIC_LATITUDE")
    longitude = os.environ.get("VANTAGE_STATIC_LONGITUDE")
    if not latitude or not longitude:
        return None

    try:
        return float(latitude), float(longitude)
    except ValueError:
        print(f"Time {_timestamp()} Invalid VANTAGE_STATIC_LATITUDE/VANTAGE_STATIC_LONGITUDE; ignoring.")
        return None


def get_location():
    static_location = _configured_static_location()
    if static_location is not None:
        latitude, longitude = static_location
        print(f"Time {_timestamp()} Using configured static location: {latitude}, {longitude}")
        return latitude, longitude

    if Geolocator is None:
        print(f"Time {_timestamp()} System location service is unavailable; skipping GPS coordinates.")
        return None, None

    async def fetch_location():
        try:
            locator = Geolocator()
            position = await locator.get_geoposition_async()
            latitude = position.coordinate.point.position.latitude
            longitude = position.coordinate.point.position.longitude
            print(f"Time {_timestamp()} Location: {latitude}, {longitude}")
            return latitude, longitude
        except Exception as exc:
            print(f"Time {_timestamp()} Failed to get system location: {exc}")
            return None, None

    def run_async_in_thread(result_holder):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            latitude, longitude = loop.run_until_complete(fetch_location())
            result_holder["latitude"] = latitude
            result_holder["longitude"] = longitude
        finally:
            loop.close()

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is not None:
        result_holder = {}
        thread = threading.Thread(target=run_async_in_thread, args=(result_holder,))
        thread.start()
        thread.join()
        latitude = result_holder.get("latitude")
        longitude = result_holder.get("longitude")
    else:
        latitude, longitude = asyncio.run(fetch_location())

    return latitude, longitude


def convert_to_exif_coords(value):
    degrees = int(value)
    minutes_float = abs((value - degrees) * 60)
    minutes = int(minutes_float)
    seconds = int((minutes_float - minutes) * 6000)
    return ((degrees, 1), (minutes, 1), (seconds, 100))


def save_image_with_gps(photo_path, frame, latitude, longitude):
    cv2.imwrite(photo_path, frame)

    if latitude is None or longitude is None:
        print(f"Time {_timestamp()} Location unavailable; skipping GPS EXIF for {photo_path}")
        return

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: "N" if latitude >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: convert_to_exif_coords(abs(latitude)),
        piexif.GPSIFD.GPSLongitudeRef: "E" if longitude >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: convert_to_exif_coords(abs(longitude)),
    }

    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, photo_path)
