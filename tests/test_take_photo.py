import gc
import os
import tempfile
import sys
import threading
import time
import types
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np

try:
    from src.manager.take_photo import take_a_photo
except ModuleNotFoundError as exc:
    if exc.name != "cv2":
        raise
    fake_cv2 = types.SimpleNamespace(
        getTickCount=lambda: 1,
        getTickFrequency=lambda: 1.0,
    )
    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        from src.manager.take_photo import take_a_photo


class TakePhotoTests(unittest.TestCase):
    def test_presence_photo_coordinator_deduplicates_pending_and_successful_minute(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        save_started = threading.Event()
        release_save = threading.Event()
        save_completed = threading.Event()
        save_calls = []

        def blocking_save(*args, **kwargs):
            save_calls.append((args, kwargs))
            save_started.set()
            self.assertTrue(release_save.wait(timeout=2))
            return "presence-photo.jpg"

        gate = take_a_photo.PresencePhotoMinuteGate()
        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=blocking_save,
            gate=gate,
        )
        self.assertTrue(coordinator._worker.daemon)

        try:
            accepted = coordinator.submit(
                frame,
                "photos",
                captured_at=captured_at,
                location_provider=lambda: (1.0, 2.0),
                on_success=lambda _path: save_completed.set(),
            )
            self.assertTrue(save_started.wait(timeout=2))
            duplicate_pending = coordinator.submit(
                frame,
                "photos",
                captured_at=captured_at + timedelta(seconds=10),
            )
            release_save.set()
            self.assertTrue(save_completed.wait(timeout=2))
            duplicate_success = coordinator.submit(
                frame,
                "photos",
                captured_at=captured_at + timedelta(seconds=20),
            )

            self.assertTrue(accepted)
            self.assertFalse(duplicate_pending)
            self.assertFalse(duplicate_success)
            self.assertEqual(len(save_calls), 1)
            self.assertIs(save_calls[0][0][0], frame)
        finally:
            release_save.set()
            self.assertTrue(coordinator.close(timeout=2))

    def test_presence_photo_coordinator_releases_failed_minute_for_retry(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        first_failure = threading.Event()
        retry_completed = threading.Event()
        attempts = []
        saved_paths = []

        def flaky_save(*_args, **_kwargs):
            attempts.append(None)
            if len(attempts) == 1:
                raise OSError("storage unavailable")
            return "retry-photo.jpg"

        gate = take_a_photo.PresencePhotoMinuteGate()
        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=flaky_save,
            gate=gate,
        )
        try:
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=captured_at,
                    on_failure=lambda _exc: first_failure.set(),
                )
            )
            self.assertTrue(first_failure.wait(timeout=2))
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=captured_at + timedelta(seconds=1),
                    on_success=lambda path: (
                        saved_paths.append(path),
                        retry_completed.set(),
                    ),
                )
            )
            self.assertTrue(retry_completed.wait(timeout=2))

            self.assertEqual(len(attempts), 2)
            self.assertEqual(saved_paths, ["retry-photo.jpg"])
        finally:
            self.assertTrue(coordinator.close(timeout=2))

    def test_presence_photo_coordinator_bounds_blocked_worker_queue(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        first_minute = datetime(2026, 7, 26, 14, 25, 7)
        save_started = threading.Event()
        release_save = threading.Event()
        three_completed = threading.Event()
        retry_completed = threading.Event()
        completed_minutes = []

        def blocking_save(*_args, **kwargs):
            save_started.set()
            self.assertTrue(release_save.wait(timeout=2))
            completed_minutes.append(kwargs["captured_at"].minute)
            if len(completed_minutes) == 3:
                three_completed.set()
            if len(completed_minutes) == 4:
                retry_completed.set()
            return f"photo-{kwargs['captured_at'].minute}.jpg"

        gate = take_a_photo.PresencePhotoMinuteGate()
        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=blocking_save,
            max_queue_size=2,
            gate=gate,
        )
        try:
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=first_minute,
                )
            )
            self.assertTrue(save_started.wait(timeout=2))
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=first_minute + timedelta(minutes=1),
                )
            )
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=first_minute + timedelta(minutes=2),
                )
            )
            rejected_time = first_minute + timedelta(minutes=3)
            self.assertFalse(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=rejected_time,
                )
            )
            rejected_key = coordinator._minute_identity(
                "photos",
                rejected_time,
            )
            self.assertEqual(len(coordinator._pending_minutes), 3)
            self.assertNotIn(rejected_key, coordinator._pending_minutes)
            self.assertFalse(
                gate.is_reserved("photos", captured_at=rejected_time)
            )

            release_save.set()
            self.assertTrue(three_completed.wait(timeout=2))
            self.assertTrue(
                coordinator.submit(
                    frame,
                    "photos",
                    captured_at=rejected_time + timedelta(seconds=1),
                )
            )
            self.assertTrue(retry_completed.wait(timeout=2))
            self.assertEqual(len(completed_minutes), 4)
        finally:
            release_save.set()
            self.assertTrue(coordinator.close(timeout=2))

    def test_presence_photo_coordinator_close_discards_queue_and_joins_worker(self):
        class FrameToken:
            pass

        first_minute = datetime(2026, 7, 26, 14, 25, 7)
        save_started = threading.Event()
        release_save = threading.Event()
        close_finished = threading.Event()
        close_results = []

        def blocking_save(*_args, **_kwargs):
            save_started.set()
            release_save.wait(timeout=2)
            return "active-photo.jpg"

        gate = take_a_photo.PresencePhotoMinuteGate()
        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=blocking_save,
            max_queue_size=2,
            gate=gate,
        )
        active_frame = FrameToken()
        queued_frame_one = FrameToken()
        queued_frame_two = FrameToken()
        queued_ref_one = weakref.ref(queued_frame_one)
        queued_ref_two = weakref.ref(queued_frame_two)
        try:
            self.assertTrue(
                coordinator.submit(
                    active_frame,
                    "photos",
                    captured_at=first_minute,
                )
            )
            self.assertTrue(save_started.wait(timeout=2))
            self.assertTrue(
                coordinator.submit(
                    queued_frame_one,
                    "photos",
                    captured_at=first_minute + timedelta(minutes=1),
                )
            )
            self.assertTrue(
                coordinator.submit(
                    queued_frame_two,
                    "photos",
                    captured_at=first_minute + timedelta(minutes=2),
                )
            )
            del queued_frame_one
            del queued_frame_two

            def close_coordinator():
                close_results.append(coordinator.close(timeout=2))
                close_finished.set()

            close_thread = threading.Thread(target=close_coordinator)
            close_thread.start()
            deadline = time.monotonic() + 1
            while not coordinator._closed and time.monotonic() < deadline:
                time.sleep(0.01)
            gc.collect()

            self.assertTrue(coordinator._closed)
            self.assertEqual(len(coordinator._pending_minutes), 1)
            self.assertTrue(
                gate.is_reserved("photos", captured_at=first_minute)
            )
            self.assertFalse(
                gate.is_reserved(
                    "photos",
                    captured_at=first_minute + timedelta(minutes=1),
                )
            )
            self.assertFalse(
                gate.is_reserved(
                    "photos",
                    captured_at=first_minute + timedelta(minutes=2),
                )
            )
            self.assertIsNone(queued_ref_one())
            self.assertIsNone(queued_ref_two())
            rejected_after_close = first_minute + timedelta(minutes=3)
            self.assertFalse(
                coordinator.submit(
                    FrameToken(),
                    "photos",
                    captured_at=rejected_after_close,
                )
            )
            self.assertFalse(
                gate.is_reserved(
                    "photos",
                    captured_at=rejected_after_close,
                )
            )

            release_save.set()
            self.assertTrue(close_finished.wait(timeout=2))
            close_thread.join(timeout=2)
            self.assertEqual(close_results, [True])
            self.assertFalse(coordinator._worker.is_alive())
            self.assertFalse(
                gate.is_reserved("photos", captured_at=first_minute)
            )
            self.assertTrue(coordinator.close(timeout=2))
        finally:
            release_save.set()
            coordinator.close(timeout=2)

    def test_coordinator_reservation_prevents_later_direct_save_from_winning(self):
        first_frame = np.full((4, 4, 3), 1, dtype=np.uint8)
        later_frame = np.full((4, 4, 3), 2, dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()
        save_started = threading.Event()
        release_save = threading.Event()
        save_completed = threading.Event()
        saved_frames = []
        first_path = "photo_20260726_142507.jpg"

        def blocking_save(frame, *_args, **_kwargs):
            saved_frames.append(frame)
            save_started.set()
            self.assertTrue(release_save.wait(timeout=2))
            return first_path

        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=blocking_save,
            gate=gate,
        )
        try:
            self.assertTrue(
                coordinator.submit(
                    first_frame,
                    "photos",
                    captured_at=captured_at,
                    on_success=lambda _path: save_completed.set(),
                )
            )
            self.assertTrue(save_started.wait(timeout=2))

            with patch.object(
                take_a_photo,
                "detect_presence_face_count",
                return_value=1,
            ), patch.object(
                take_a_photo,
                "save_image_with_gps",
            ) as direct_write:
                later_result = take_a_photo.take_photo(
                    object(),
                    1.0,
                    2.0,
                    "photos",
                    pre_captured_frame=later_frame,
                    captured_at=captured_at + timedelta(seconds=10),
                    photo_gate=gate,
                )

            self.assertEqual(later_result, (True, None))
            direct_write.assert_not_called()
            release_save.set()
            self.assertTrue(save_completed.wait(timeout=2))

            cached_path = take_a_photo.save_presence_photo_once_per_minute(
                later_frame,
                "photos",
                captured_at=captured_at + timedelta(seconds=20),
                gate=gate,
            )
            self.assertEqual(cached_path, first_path)
            self.assertEqual(len(saved_frames), 1)
            self.assertIs(saved_frames[0], first_frame)
        finally:
            release_save.set()
            self.assertTrue(coordinator.close(timeout=2))

    def test_failed_worker_reservation_allows_later_direct_frame_to_save(self):
        first_frame = np.full((4, 4, 3), 1, dtype=np.uint8)
        later_frame = np.full((4, 4, 3), 2, dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()
        failure_seen = threading.Event()

        def fail_save(*_args, **_kwargs):
            raise OSError("storage unavailable")

        coordinator = take_a_photo.PresencePhotoSaveCoordinator(
            save_fn=fail_save,
            gate=gate,
        )
        try:
            self.assertTrue(
                coordinator.submit(
                    first_frame,
                    "photos",
                    captured_at=captured_at,
                    on_failure=lambda _exc: failure_seen.set(),
                )
            )
            self.assertTrue(failure_seen.wait(timeout=2))
            self.assertFalse(
                gate.is_reserved("photos", captured_at=captured_at)
            )

            with patch.object(
                take_a_photo,
                "save_image_with_gps",
            ) as direct_write:
                later_path = take_a_photo.save_presence_photo_once_per_minute(
                    later_frame,
                    "photos",
                    captured_at=captured_at + timedelta(seconds=1),
                    gate=gate,
                )

            self.assertIsNotNone(later_path)
            self.assertIs(direct_write.call_args.args[1], later_frame)
        finally:
            self.assertTrue(coordinator.close(timeout=2))

    def test_presence_photo_gate_saves_only_once_in_the_same_natural_minute(self):
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=captured_at,
                gate=gate,
            )
            duplicate_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=captured_at + timedelta(seconds=40),
                gate=gate,
            )

        self.assertIsNotNone(first_path)
        self.assertEqual(duplicate_path, first_path)
        mock_save.assert_called_once()
        self.assertIs(mock_save.call_args.args[1], frame)
        self.assertIn("photo_20260726_142507.jpg", first_path)

    def test_presence_photo_gate_does_not_duplicate_after_out_of_order_minute(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        minute_1425 = datetime(2026, 7, 26, 14, 25, 30)
        minute_1426 = datetime(2026, 7, 26, 14, 26, 10)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_1426_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=minute_1426,
                gate=gate,
            )
            path_1425 = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=minute_1425,
                gate=gate,
            )
            repeated_1426_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=minute_1426 + timedelta(seconds=20),
                gate=gate,
            )

        self.assertIsNotNone(path_1425)
        self.assertEqual(repeated_1426_path, first_1426_path)
        self.assertEqual(mock_save.call_count, 2)

    def test_presence_photo_gate_allows_each_root_to_save_in_the_same_minute(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as first_root, tempfile.TemporaryDirectory() as second_root, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                first_root,
                1.0,
                2.0,
                captured_at=captured_at,
                gate=gate,
            )
            second_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                second_root,
                1.0,
                2.0,
                captured_at=captured_at,
                gate=gate,
            )

        self.assertIsNotNone(first_path)
        self.assertIsNotNone(second_path)
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(mock_save.call_count, 2)

    def test_presence_photo_gate_preserves_absolute_root_spelling_for_disk_path(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()
        absolute_root = r"C:\Photos\MixedCase"
        normalized_root = r"c:\photos\mixedcase"

        with patch.object(
            take_a_photo.os.path,
            "abspath",
            return_value=absolute_root,
        ), patch.object(
            take_a_photo.os.path,
            "normcase",
            return_value=normalized_root,
        ), patch.object(
            take_a_photo.os,
            "makedirs",
        ) as mock_makedirs, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            photo_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                r"C:\ignored-input",
                1.0,
                2.0,
                captured_at=captured_at,
                gate=gate,
            )

        expected_folder = os.path.join(
            absolute_root,
            "2026",
            "07",
            "26",
            "14",
        )
        self.assertTrue(photo_path.startswith(absolute_root))
        mock_makedirs.assert_called_once_with(expected_folder, exist_ok=True)
        self.assertEqual(mock_save.call_args.args[0], photo_path)

    def test_presence_photo_gate_keeps_a_full_day_of_minute_deduplication(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        first_minute = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_path = None
            for minute_offset in range(10):
                photo_path = take_a_photo.save_presence_photo_once_per_minute(
                    frame,
                    tmpdir,
                    1.0,
                    2.0,
                    captured_at=first_minute + timedelta(minutes=minute_offset),
                    gate=gate,
                )
                if minute_offset == 0:
                    first_path = photo_path

            revisited_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=first_minute + timedelta(seconds=20),
                gate=gate,
            )

        self.assertEqual(revisited_path, first_path)
        self.assertEqual(mock_save.call_count, 10)

    def test_presence_photo_gate_accepts_first_save_in_next_natural_minute(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 59)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=captured_at,
                gate=gate,
            )
            next_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=captured_at + timedelta(seconds=1),
                gate=gate,
            )

        self.assertIsNotNone(first_path)
        self.assertIsNotNone(next_path)
        self.assertNotEqual(first_path, next_path)
        self.assertEqual(mock_save.call_count, 2)

    def test_presence_photo_gate_retries_same_minute_after_storage_failure(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
            side_effect=[OSError("storage unavailable"), None],
        ) as mock_save:
            with self.assertRaisesRegex(OSError, "storage unavailable"):
                take_a_photo.save_presence_photo_once_per_minute(
                    frame,
                    tmpdir,
                    1.0,
                    2.0,
                    captured_at=captured_at,
                    gate=gate,
                )
            retry_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                1.0,
                2.0,
                captured_at=captured_at + timedelta(seconds=1),
                gate=gate,
            )

        self.assertIsNotNone(retry_path)
        self.assertEqual(mock_save.call_count, 2)

    def test_presence_photo_gate_resolves_location_only_for_an_accepted_save(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            location_calls = []

            def location_provider():
                location_calls.append(None)
                return 1.25, 2.5

            first_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                captured_at=captured_at,
                location_provider=location_provider,
                gate=gate,
            )
            duplicate_path = take_a_photo.save_presence_photo_once_per_minute(
                frame,
                tmpdir,
                captured_at=captured_at + timedelta(seconds=10),
                location_provider=location_provider,
                gate=gate,
            )

        self.assertIsNotNone(first_path)
        self.assertEqual(duplicate_path, first_path)
        self.assertEqual(len(location_calls), 1)
        mock_save.assert_called_once_with(first_path, frame, 1.25, 2.5)

    def test_presence_photo_gate_allows_only_one_concurrent_same_minute_save(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()
        ready = threading.Barrier(8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            def attempt_save(_index):
                ready.wait()
                return take_a_photo.save_presence_photo_once_per_minute(
                    frame,
                    tmpdir,
                    1.0,
                    2.0,
                    captured_at=captured_at,
                    gate=gate,
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                paths = list(executor.map(attempt_save, range(8)))

        self.assertEqual(mock_save.call_count, 1)
        saved_paths = [path for path in paths if path is not None]
        self.assertEqual(len(saved_paths), 1)
        self.assertEqual(paths.count(None), 7)

    def test_take_photo_keeps_presence_contract_when_minute_gate_suppresses_duplicate(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        captured_at = datetime(2026, 7, 26, 14, 25, 7)
        gate = take_a_photo.PresencePhotoMinuteGate()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=1,
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            first_result = take_a_photo.take_photo(
                object(),
                1.0,
                2.0,
                tmpdir,
                pre_captured_frame=frame,
                captured_at=captured_at,
                photo_gate=gate,
            )
            duplicate_result = take_a_photo.take_photo(
                object(),
                1.0,
                2.0,
                tmpdir,
                pre_captured_frame=frame,
                captured_at=captured_at + timedelta(seconds=20),
                photo_gate=gate,
            )

        self.assertTrue(first_result[0])
        self.assertIsNotNone(first_result[1])
        self.assertEqual(duplicate_result, (True, first_result[1]))
        mock_save.assert_called_once()

    def test_presence_face_count_delegates_to_yunet_presence_at_half_confidence(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with patch.object(
            take_a_photo,
            "detect_presence_count",
            return_value=1,
        ) as mock_detect:
            result = take_a_photo.detect_presence_face_count(frame)

        self.assertEqual(result, 1)
        mock_detect.assert_called_once_with(frame, conf=0.50)

    def test_take_photo_uses_pre_captured_frame_without_reading_camera(self):
        frame = np.full((4, 4, 3), 7, dtype=np.uint8)
        camera = object()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            side_effect=AssertionError("pre-captured frame must not read camera"),
        ) as mock_capture, patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=0,
        ) as mock_detect, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            result = take_a_photo.take_photo(
                camera,
                0.0,
                0.0,
                tmpdir,
                pre_captured_frame=frame,
            )

        self.assertEqual(result, (False, None))
        mock_capture.assert_not_called()
        mock_detect.assert_called_once()
        self.assertIs(mock_detect.call_args.args[0], frame)
        mock_save.assert_not_called()

    def test_take_photo_explicit_unavailable_frame_does_not_fall_back_to_camera(self):
        invalid_frames = (
            None,
            np.empty((0, 0, 3), dtype=np.uint8),
            np.array([1, 2, 3], dtype=np.uint8),
        )

        for frame in invalid_frames:
            with tempfile.TemporaryDirectory() as tmpdir, patch.object(
                take_a_photo,
                "capture_best_photo",
                side_effect=AssertionError("explicit frame must not read camera"),
            ) as mock_capture, patch.object(
                take_a_photo,
                "detect_presence_face_count",
            ) as mock_detect, patch.object(
                take_a_photo,
                "save_image_with_gps",
            ) as mock_save:
                result = take_a_photo.take_photo(
                    object(),
                    0.0,
                    0.0,
                    tmpdir,
                    pre_captured_frame=frame,
                )

            self.assertEqual(result, (None, None))
            mock_capture.assert_not_called()
            mock_detect.assert_not_called()
            mock_save.assert_not_called()

    def test_take_photo_returns_unknown_without_running_detection_when_capture_fails(self):
        camera = object()
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=None,
        ) as mock_capture, patch.object(
            take_a_photo,
            "detect_presence_face_count",
        ) as mock_detect, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save, patch("builtins.print") as mock_print:
            result = take_a_photo.take_photo(camera, 0.0, 0.0, tmpdir)

        self.assertEqual(result, (None, None))
        mock_capture.assert_called_once_with(camera)
        mock_detect.assert_not_called()
        mock_save.assert_not_called()
        log_text = "\n".join(str(item) for item in mock_print.call_args_list)
        self.assertIn("Camera capture unavailable", log_text)
        self.assertNotIn("YOLO", log_text)

    def test_take_photo_returns_unknown_when_camera_capture_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            side_effect=OSError("camera disconnected"),
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
        ) as mock_detect, patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save, patch("builtins.print") as mock_print:
            result = take_a_photo.take_photo(object(), 0.0, 0.0, tmpdir)

        self.assertEqual(result, (None, None))
        mock_detect.assert_not_called()
        mock_save.assert_not_called()
        log_text = "\n".join(str(item) for item in mock_print.call_args_list)
        self.assertIn("Camera capture unavailable", log_text)
        self.assertIn("camera disconnected", log_text)

    def test_take_photo_returns_unknown_for_empty_or_invalid_frame(self):
        invalid_frames = (
            np.empty((0, 0, 3), dtype=np.uint8),
            np.array([1, 2, 3], dtype=np.uint8),
        )

        for frame in invalid_frames:
            with self.subTest(shape=frame.shape), tempfile.TemporaryDirectory() as tmpdir, patch.object(
                take_a_photo,
                "capture_best_photo",
                return_value=frame,
            ), patch.object(
                take_a_photo,
                "detect_presence_face_count",
                return_value=0,
            ) as mock_detect, patch.object(
                take_a_photo,
                "save_image_with_gps",
            ) as mock_save, patch("builtins.print") as mock_print:
                result = take_a_photo.take_photo(object(), 0.0, 0.0, tmpdir)

            self.assertEqual(result, (None, None))
            mock_detect.assert_not_called()
            mock_save.assert_not_called()
            log_text = "\n".join(str(item) for item in mock_print.call_args_list)
            self.assertIn("Camera capture unavailable", log_text)

    def test_take_photo_saves_photo_when_presence_is_detected(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=1,
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertTrue(success)
        self.assertIsNotNone(photo_path)
        mock_save.assert_called_once()
        self.assertEqual(mock_save.call_args[0][1].shape, frame.shape)

    def test_take_photo_returns_unknown_when_presence_detection_is_unavailable(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            side_effect=FileNotFoundError("missing model"),
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertIsNone(success)
        self.assertIsNone(photo_path)
        mock_save.assert_not_called()

    def test_unavailable_presence_clears_previous_live_box_and_returns_unknown(self):
        from src import server
        from src.services.person_detection import PresenceDetectionUnavailable

        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        previous_box = (0, 0, 3, 3)
        boxes_seen_before_failure = []

        def detect_live_presence(*_args, **_kwargs):
            if not boxes_seen_before_failure:
                boxes_seen_before_failure.append(None)
                return [previous_box]
            boxes_seen_before_failure[0] = list(server.state.person_boxes)
            server.state.is_running = False
            raise PresenceDetectionUnavailable("YuNet inference unavailable")

        with server.state.lock:
            original_is_running = server.state.is_running
            original_latest_frame = server.state.latest_frame
            original_latest_frame_published_at = (
                server.state.latest_frame_published_at
            )
            original_person_boxes = list(server.state.person_boxes)
            server.state.is_running = True
            server.state.latest_frame = frame
            server.state.latest_frame_published_at = 0.0
            server.state.person_boxes = []

        try:
            with (
                patch.object(server, "get_face_detector", return_value=object()),
                patch.object(server, "should_run_face_detection", return_value=True),
                patch.object(
                    server,
                    "wait_for_next_inference_start",
                    side_effect=[0.0, 1.0],
                    create=True,
                ),
                patch.object(
                    server,
                    "detect_foreground_presence_face_boxes",
                    side_effect=detect_live_presence,
                ),
                patch.object(server.time, "sleep"),
                patch("builtins.print"),
            ):
                server.face_detection_loop()

            with tempfile.TemporaryDirectory() as tmpdir, patch.object(
                take_a_photo,
                "detect_presence_face_count",
                side_effect=PresenceDetectionUnavailable(
                    "YuNet inference unavailable"
                ),
            ), patch.object(take_a_photo, "save_image_with_gps") as mock_save:
                presence_status, photo_path = take_a_photo.take_photo(
                    object(),
                    1.0,
                    2.0,
                    tmpdir,
                    pre_captured_frame=frame,
                )

            self.assertEqual(boxes_seen_before_failure[0], [previous_box])
            self.assertEqual(server.state.person_boxes, [])
            self.assertIsNone(presence_status)
            self.assertIsNone(photo_path)
            mock_save.assert_not_called()
        finally:
            with server.state.lock:
                server.state.is_running = original_is_running
                server.state.latest_frame = original_latest_frame
                server.state.latest_frame_published_at = (
                    original_latest_frame_published_at
                )
                server.state.person_boxes = original_person_boxes

    def test_take_photo_returns_absent_after_successful_detection_finds_no_presence(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=0,
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertFalse(success)
        self.assertIsNone(photo_path)
        mock_save.assert_not_called()

    def test_take_photo_keeps_presence_when_photo_storage_fails(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=1,
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
            side_effect=OSError("storage unavailable"),
        ):
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertTrue(success)
        self.assertIsNone(photo_path)

    def test_take_photo_keeps_presence_when_photo_directory_creation_fails(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            return_value=1,
        ), patch.object(
            take_a_photo.os,
            "makedirs",
            side_effect=OSError("directory unavailable"),
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save, patch("builtins.print") as mock_print:
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertTrue(success)
        self.assertIsNone(photo_path)
        mock_save.assert_not_called()
        log_text = "\n".join(str(item) for item in mock_print.call_args_list)
        self.assertIn("Detected presence but failed to store photo", log_text)


if __name__ == "__main__":
    unittest.main()
