import cv2
import os
import threading
from collections import OrderedDict
from datetime import datetime

from .get_best_photo import capture_best_photo
from ..get_location import save_image_with_gps
from src.services.person_detection import (
    PRESENCE_DETECTION_CONFIDENCE,
    detect_presence_count,
)


_PRE_CAPTURED_FRAME_UNSET = object()


class PresencePhotoMinuteGate:
    # Keep a full day of recent minute keys so normal continuous operation and
    # small clock rollbacks remain deduplicated. Older keys, or all keys after a
    # process restart, intentionally begin a new approved capture window.
    _MAX_CACHED_MINUTES_PER_ROOT = 24 * 60

    def __init__(self):
        self._lock = threading.Lock()
        self._saved_photo_by_minute = {}
        self._minute_order_by_root = {}

    def save(
        self,
        frame,
        photos_path,
        latitude=None,
        longitude=None,
        *,
        captured_at=None,
        location_provider=None,
    ):
        capture_time = captured_at if captured_at is not None else datetime.now()
        absolute_root = os.path.abspath(os.fspath(photos_path))
        normalized_root = os.path.normcase(absolute_root)
        minute_key = capture_time.strftime("%Y%m%d%H%M")
        cache_key = (normalized_root, minute_key)

        with self._lock:
            cached_photo_path = self._saved_photo_by_minute.get(cache_key)
            if cached_photo_path is not None:
                minute_order = self._minute_order_by_root[normalized_root]
                minute_order.move_to_end(minute_key)
                return cached_photo_path

            resolved_latitude = latitude
            resolved_longitude = longitude
            if location_provider is not None:
                resolved_latitude, resolved_longitude = location_provider()

            daily_folder = os.path.join(
                absolute_root,
                capture_time.strftime("%Y"),
                capture_time.strftime("%m"),
                capture_time.strftime("%d"),
                capture_time.strftime("%H"),
            )
            os.makedirs(daily_folder, exist_ok=True)
            photo_name = f"photo_{capture_time.strftime('%Y%m%d_%H%M%S')}.jpg"
            photo_path = os.path.join(daily_folder, photo_name)
            save_image_with_gps(
                photo_path,
                frame,
                resolved_latitude,
                resolved_longitude,
            )
            self._saved_photo_by_minute[cache_key] = photo_path
            minute_order = self._minute_order_by_root.setdefault(
                normalized_root,
                OrderedDict(),
            )
            minute_order[minute_key] = None
            while len(minute_order) > self._MAX_CACHED_MINUTES_PER_ROOT:
                expired_minute_key, _ = minute_order.popitem(last=False)
                self._saved_photo_by_minute.pop(
                    (normalized_root, expired_minute_key),
                    None,
                )
            return photo_path


_SHARED_PRESENCE_PHOTO_GATE = PresencePhotoMinuteGate()


def save_presence_photo_once_per_minute(
    frame,
    photos_path,
    latitude=None,
    longitude=None,
    *,
    captured_at=None,
    location_provider=None,
    gate=None,
):
    active_gate = gate if gate is not None else _SHARED_PRESENCE_PHOTO_GATE
    return active_gate.save(
        frame,
        photos_path,
        latitude,
        longitude,
        captured_at=captured_at,
        location_provider=location_provider,
    )


def detect_presence_face_count(image):
    return detect_presence_count(image, conf=PRESENCE_DETECTION_CONFIDENCE)


def _is_valid_capture_frame(frame):
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    shape = getattr(frame, "shape", ())
    return len(shape) >= 2 and int(shape[0]) > 0 and int(shape[1]) > 0


def take_photo(
    cam,
    latitude,
    longitude,
    photos_path,
    pre_captured_frame=_PRE_CAPTURED_FRAME_UNSET,
    *,
    captured_at=None,
    photo_gate=None,
):
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Taking photo")
    if pre_captured_frame is _PRE_CAPTURED_FRAME_UNSET:
        try:
            frame = capture_best_photo(cam)
        except Exception as exc:
            print(
                f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"Camera capture unavailable; skipping presence detection: {exc}"
            )
            return None, None
    else:
        frame = pre_captured_frame

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
        try:
            photo_path = save_presence_photo_once_per_minute(
                frame,
                photos_path,
                latitude,
                longitude,
                captured_at=captured_at,
                gate=photo_gate,
            )
        except Exception as exc:
            print(
                f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"Detected presence but failed to store photo: {exc}"
            )
            return True, None
        print(
            f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"Presence photo available as {photo_path}"
        )
        return True, photo_path

    return False, None
