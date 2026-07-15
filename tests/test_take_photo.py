import tempfile
import sys
import types
import unittest
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
            original_person_boxes = list(server.state.person_boxes)
            server.state.is_running = True
            server.state.latest_frame = frame
            server.state.person_boxes = []

        try:
            with (
                patch.object(server, "get_face_detector", return_value=object()),
                patch.object(server, "should_run_face_detection", return_value=True),
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
