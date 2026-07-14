import tempfile
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

sys.modules.setdefault(
    "cv2",
    types.SimpleNamespace(
        getTickCount=lambda: 1,
        getTickFrequency=lambda: 1.0,
    ),
)

from src.manager.take_photo import take_a_photo


class TakePhotoTests(unittest.TestCase):
    def test_take_photo_returns_unknown_without_running_detection_when_capture_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=None,
        ), patch.object(
            take_a_photo,
            "detect_presence_face_count",
            side_effect=AssertionError("detection should not run without a frame"),
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
            side_effect=AssertionError("save should not run without a frame"),
        ), patch("builtins.print") as mock_print:
            result = take_a_photo.take_photo(object(), 0.0, 0.0, tmpdir)

        self.assertEqual(result, (None, None))
        log_text = "\n".join(str(item) for item in mock_print.call_args_list)
        self.assertIn("skipping face detection", log_text)
        self.assertNotIn("YOLO", log_text)

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
