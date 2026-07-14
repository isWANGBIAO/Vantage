import cv2
import os
from datetime import datetime

from .get_best_photo import capture_best_photo
from ..get_location import save_image_with_gps
from src.services.person_detection import (
    PRESENCE_DETECTION_CONFIDENCE,
    detect_presence_count,
)


def detect_presence_face_count(image):
    return detect_presence_count(image, conf=PRESENCE_DETECTION_CONFIDENCE)


def _is_valid_capture_frame(frame):
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    shape = getattr(frame, "shape", ())
    return len(shape) >= 2 and int(shape[0]) > 0 and int(shape[1]) > 0


def take_photo(cam, latitude, longitude, photos_path):
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Taking photo")
    try:
        frame = capture_best_photo(cam)
    except Exception as exc:
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Camera capture unavailable; skipping presence detection: {exc}"
        )
        return None, None

    if not _is_valid_capture_frame(frame):
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            "Camera capture unavailable; empty or invalid frame; skipping presence detection"
        )
        return None, None

    try:
        t1 = cv2.getTickCount()
        face_count = detect_presence_face_count(frame)
        t2 = cv2.getTickCount()
        elapsed = (t2 - t1) / cv2.getTickFrequency()
        fps = 1.0 / elapsed if elapsed else 0.0
    except Exception as exc:
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Presence detection unavailable; skipping photo save: {exc}"
        )
        return None, None

    if face_count:
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Detected {face_count} face(s) indicating presence in the photo Time: {elapsed}, FPS: {fps}"
        )
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Saving photo")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_name = f"photo_{timestamp}.jpg"

        try:
            now = datetime.now()
            daily_folder = os.path.join(
                photos_path,
                now.strftime("%Y"),
                now.strftime("%m"),
                now.strftime("%d"),
                now.strftime("%H"),
            )
            os.makedirs(daily_folder, exist_ok=True)
            photo_path = os.path.join(daily_folder, photo_name)
            save_image_with_gps(photo_path, frame, latitude, longitude)
        except Exception as exc:
            print(
                f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"Detected presence but failed to store photo: {exc}"
            )
            return True, None
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Photo taken and saved as {photo_path}")
        return True, photo_path

    return False, None
