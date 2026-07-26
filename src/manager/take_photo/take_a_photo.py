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


class _PresencePhotoReservation:
    __slots__ = ("cache_key", "normalized_root", "minute_key", "token")

    def __init__(self, normalized_root, minute_key):
        self.cache_key = (normalized_root, minute_key)
        self.normalized_root = normalized_root
        self.minute_key = minute_key
        self.token = object()


class PresencePhotoMinuteGate:
    # Keep a full day of recent minute keys so normal continuous operation and
    # small clock rollbacks remain deduplicated. Older keys, or all keys after a
    # process restart, intentionally begin a new approved capture window.
    _MAX_CACHED_MINUTES_PER_ROOT = 24 * 60

    def __init__(self):
        self._lock = threading.Lock()
        self._saved_photo_by_minute = {}
        self._minute_order_by_root = {}
        self._reservation_by_minute = {}

    @staticmethod
    def _minute_identity(photos_path, captured_at):
        absolute_root = os.path.abspath(os.fspath(photos_path))
        normalized_root = os.path.normcase(absolute_root)
        minute_key = captured_at.strftime("%Y%m%d%H%M")
        return absolute_root, normalized_root, minute_key

    def cached_path(self, photos_path, *, captured_at):
        _, normalized_root, minute_key = self._minute_identity(
            photos_path,
            captured_at,
        )
        cache_key = (normalized_root, minute_key)
        with self._lock:
            photo_path = self._saved_photo_by_minute.get(cache_key)
            if photo_path is not None:
                self._minute_order_by_root[normalized_root].move_to_end(
                    minute_key
                )
            return photo_path

    def reserve(self, photos_path, *, captured_at):
        _, normalized_root, minute_key = self._minute_identity(
            photos_path,
            captured_at,
        )
        cache_key = (normalized_root, minute_key)
        with self._lock:
            if (
                cache_key in self._saved_photo_by_minute
                or cache_key in self._reservation_by_minute
            ):
                return None
            reservation = _PresencePhotoReservation(
                normalized_root,
                minute_key,
            )
            self._reservation_by_minute[cache_key] = reservation
            return reservation

    def is_reserved(self, photos_path, *, captured_at):
        _, normalized_root, minute_key = self._minute_identity(
            photos_path,
            captured_at,
        )
        with self._lock:
            return (
                normalized_root,
                minute_key,
            ) in self._reservation_by_minute

    def _is_active_reservation(self, reservation):
        if not isinstance(reservation, _PresencePhotoReservation):
            return False
        with self._lock:
            return (
                self._reservation_by_minute.get(reservation.cache_key)
                is reservation
            )

    def release(self, reservation):
        if not isinstance(reservation, _PresencePhotoReservation):
            return False
        with self._lock:
            if (
                self._reservation_by_minute.get(reservation.cache_key)
                is not reservation
            ):
                return False
            self._reservation_by_minute.pop(reservation.cache_key, None)
            return True

    def commit(self, reservation, photo_path):
        if (
            not isinstance(reservation, _PresencePhotoReservation)
            or not photo_path
        ):
            return False
        with self._lock:
            current_reservation = self._reservation_by_minute.get(
                reservation.cache_key
            )
            if current_reservation is not reservation:
                return (
                    self._saved_photo_by_minute.get(reservation.cache_key)
                    == photo_path
                )
            self._reservation_by_minute.pop(reservation.cache_key, None)
            self._saved_photo_by_minute[reservation.cache_key] = photo_path
            minute_order = self._minute_order_by_root.setdefault(
                reservation.normalized_root,
                OrderedDict(),
            )
            minute_order[reservation.minute_key] = None
            minute_order.move_to_end(reservation.minute_key)
            while len(minute_order) > self._MAX_CACHED_MINUTES_PER_ROOT:
                expired_minute_key, _ = minute_order.popitem(last=False)
                self._saved_photo_by_minute.pop(
                    (reservation.normalized_root, expired_minute_key),
                    None,
                )
            return True

    def save(
        self,
        frame,
        photos_path,
        latitude=None,
        longitude=None,
        *,
        captured_at=None,
        location_provider=None,
        reservation=None,
    ):
        capture_time = captured_at if captured_at is not None else datetime.now()
        absolute_root, normalized_root, minute_key = self._minute_identity(
            photos_path,
            capture_time,
        )
        cache_key = (normalized_root, minute_key)
        active_reservation = reservation
        if active_reservation is None:
            cached_photo_path = self.cached_path(
                photos_path,
                captured_at=capture_time,
            )
            if cached_photo_path is not None:
                return cached_photo_path
            active_reservation = self.reserve(
                photos_path,
                captured_at=capture_time,
            )
            if active_reservation is None:
                return self.cached_path(
                    photos_path,
                    captured_at=capture_time,
                )
        if (
            not isinstance(active_reservation, _PresencePhotoReservation)
            or active_reservation.cache_key != cache_key
            or not self._is_active_reservation(active_reservation)
        ):
            return None

        try:
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
        except Exception:
            self.release(active_reservation)
            raise
        if self.commit(active_reservation, photo_path):
            return photo_path
        return self.cached_path(photos_path, captured_at=capture_time)


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
    reservation=None,
):
    active_gate = gate if gate is not None else _SHARED_PRESENCE_PHOTO_GATE
    return active_gate.save(
        frame,
        photos_path,
        latitude,
        longitude,
        captured_at=captured_at,
        location_provider=location_provider,
        reservation=reservation,
    )


class PresencePhotoSaveCoordinator:
    _STOP = object()

    def __init__(self, *, save_fn=None, max_queue_size=2, gate=None):
        if (
            not isinstance(max_queue_size, int)
            or isinstance(max_queue_size, bool)
            or max_queue_size < 1
        ):
            raise ValueError("max_queue_size must be a positive integer")
        self._save_fn = save_fn
        self._gate = gate if gate is not None else _SHARED_PRESENCE_PHOTO_GATE
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._pending_minutes = set()
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
        with self._lock:
            if self._closed:
                return False

        reservation = self._gate.reserve(
            photos_path,
            captured_at=capture_time,
        )
        if reservation is None:
            return False

        accepted = False
        with self._lock:
            if not self._closed:
                self._pending_minutes.add(reservation.cache_key)
                task = {
                    "cache_key": reservation.cache_key,
                    "frame": frame,
                    "photos_path": photos_path,
                    "captured_at": capture_time,
                    "location_provider": location_provider,
                    "on_success": on_success,
                    "on_failure": on_failure,
                    "reservation": reservation,
                }
                try:
                    self._queue.put_nowait(task)
                except queue.Full:
                    self._pending_minutes.discard(reservation.cache_key)
                except Exception:
                    self._pending_minutes.discard(reservation.cache_key)
                else:
                    accepted = True
        if not accepted:
            self._gate.release(reservation)
            return False
        return True

    def close(self, *, timeout=None):
        reservations_to_release = []
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
                        reservations_to_release.append(
                            queued_task["reservation"]
                        )
                    self._queue.task_done()
                queued_task = None
            if not self._shutdown_enqueued and self._worker.is_alive():
                self._queue.put_nowait(self._STOP)
                self._shutdown_enqueued = True

        for reservation in reservations_to_release:
            self._gate.release(reservation)

        if threading.current_thread() is self._worker:
            return False
        self._worker.join(timeout=timeout)
        return not self._worker.is_alive()

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
                    gate=self._gate,
                    reservation=task["reservation"],
                )
            except Exception as exc:
                self._gate.release(task["reservation"])
                with self._lock:
                    self._pending_minutes.discard(task["cache_key"])
                callback = task["on_failure"]
                if callback is not None:
                    try:
                        callback(exc)
                    except Exception:
                        pass
            else:
                if photo_path:
                    committed = self._gate.commit(
                        task["reservation"],
                        photo_path,
                    )
                else:
                    self._gate.release(task["reservation"])
                    committed = False
                with self._lock:
                    self._pending_minutes.discard(task["cache_key"])
                callback = task["on_success"]
                if committed and callback is not None:
                    try:
                        callback(photo_path)
                    except Exception:
                        pass
            finally:
                self._queue.task_done()
                task = None


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
