import cv2
import os
import queue
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


class PresencePhotoSaveCoordinator:
    _MAX_SUCCESSFUL_MINUTES_PER_ROOT = 24 * 60
    _STOP = object()

    def __init__(self, *, save_fn=None, max_queue_size=2):
        if (
            not isinstance(max_queue_size, int)
            or isinstance(max_queue_size, bool)
            or max_queue_size < 1
        ):
            raise ValueError("max_queue_size must be a positive integer")
        self._save_fn = save_fn
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._pending_minutes = set()
        self._successful_minutes_by_root = {}
        self._closed = False
        self._shutdown_enqueued = False
        self._worker = threading.Thread(
            target=self._run,
            name="presence-photo-save",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _minute_identity(photos_path, captured_at):
        absolute_root = os.path.abspath(os.fspath(photos_path))
        normalized_root = os.path.normcase(absolute_root)
        minute_key = captured_at.strftime("%Y%m%d%H%M")
        return normalized_root, minute_key

    def submit(
        self,
        frame,
        photos_path,
        *,
        captured_at=None,
        location_provider=None,
        on_success=None,
        on_failure=None,
    ):
        capture_time = captured_at if captured_at is not None else datetime.now()
        normalized_root, minute_key = self._minute_identity(
            photos_path,
            capture_time,
        )
        cache_key = (normalized_root, minute_key)

        with self._lock:
            if self._closed:
                return False
            successful_minutes = self._successful_minutes_by_root.get(
                normalized_root,
            )
            if (
                cache_key in self._pending_minutes
                or (
                    successful_minutes is not None
                    and minute_key in successful_minutes
                )
            ):
                return False
            self._pending_minutes.add(cache_key)
            try:
                self._queue.put_nowait(
                    {
                        "cache_key": cache_key,
                        "normalized_root": normalized_root,
                        "minute_key": minute_key,
                        "frame": frame,
                        "photos_path": photos_path,
                        "captured_at": capture_time,
                        "location_provider": location_provider,
                        "on_success": on_success,
                        "on_failure": on_failure,
                    }
                )
            except queue.Full:
                self._pending_minutes.discard(cache_key)
                return False
        return True

    def close(self, *, timeout=None):
        with self._lock:
            if not self._closed:
                self._closed = True
                while True:
                    try:
                        queued_task = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if queued_task is not self._STOP:
                        self._pending_minutes.discard(
                            queued_task["cache_key"],
                        )
                    self._queue.task_done()
                queued_task = None
            if not self._shutdown_enqueued and self._worker.is_alive():
                self._queue.put_nowait(self._STOP)
                self._shutdown_enqueued = True

        if threading.current_thread() is self._worker:
            return False
        self._worker.join(timeout=timeout)
        return not self._worker.is_alive()

    def _record_success(self, normalized_root, minute_key):
        successful_minutes = self._successful_minutes_by_root.setdefault(
            normalized_root,
            OrderedDict(),
        )
        successful_minutes[minute_key] = None
        successful_minutes.move_to_end(minute_key)
        while (
            len(successful_minutes)
            > self._MAX_SUCCESSFUL_MINUTES_PER_ROOT
        ):
            successful_minutes.popitem(last=False)

    def _run(self):
        while True:
            task = self._queue.get()
            if task is self._STOP:
                self._queue.task_done()
                return
            try:
                save_fn = (
                    self._save_fn
                    if self._save_fn is not None
                    else save_presence_photo_once_per_minute
                )
                photo_path = save_fn(
                    task["frame"],
                    task["photos_path"],
                    captured_at=task["captured_at"],
                    location_provider=task["location_provider"],
                )
            except Exception as exc:
                with self._lock:
                    self._pending_minutes.discard(task["cache_key"])
                callback = task["on_failure"]
                if callback is not None:
                    try:
                        callback(exc)
                    except Exception:
                        pass
            else:
                with self._lock:
                    self._pending_minutes.discard(task["cache_key"])
                    if photo_path:
                        self._record_success(
                            task["normalized_root"],
                            task["minute_key"],
                        )
                callback = task["on_success"]
                if photo_path and callback is not None:
                    try:
                        callback(photo_path)
                    except Exception:
                        pass
            finally:
                self._queue.task_done()


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
