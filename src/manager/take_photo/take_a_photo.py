import cv2
import os
from datetime import datetime

from .get_best_photo import capture_best_photo
from ..get_location import save_image_with_gps
from src.services.person_detection import (
    PERSON_DETECTION_CONFIDENCE,
    detect_person_count,
)


def detect_camera_facing_face_count(image):
    return detect_person_count(image, conf=PERSON_DETECTION_CONFIDENCE)


def take_photo(cam, latitude, longitude, photos_path):
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Taking photo")
    frame = capture_best_photo(cam)
    if frame is None:
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Camera capture failed; skipping face detection")
        return False, None

    try:
        t1 = cv2.getTickCount()
        face_count = detect_camera_facing_face_count(frame)
        t2 = cv2.getTickCount()
        elapsed = (t2 - t1) / cv2.getTickFrequency()
        fps = 1.0 / elapsed if elapsed else 0.0
    except Exception as exc:
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Face detection unavailable; skipping photo save: {exc}"
        )
        return False, None

    if face_count:
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Detected {face_count} camera-facing face(s) in the photo Time: {elapsed}, FPS: {fps}"
        )
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Saving photo")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_name = f"photo_{timestamp}.jpg"

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
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Photo taken and saved as {photo_path}")
        return True, photo_path

    return False, None
