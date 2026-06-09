import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from src.manager.take_photo import take_a_photo


class TakePhotoTests(unittest.TestCase):
    def test_take_photo_returns_false_without_running_detection_when_capture_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=None,
        ), patch.object(
            take_a_photo,
            "detect_person_YOLO",
            side_effect=AssertionError("detection should not run without a frame"),
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
            side_effect=AssertionError("save should not run without a frame"),
        ):
            result = take_a_photo.take_photo(object(), 0.0, 0.0, tmpdir)

        self.assertEqual(result, (False, None))

    def test_take_photo_saves_photo_when_person_is_detected(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_person_YOLO",
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

    def test_take_photo_skips_save_when_person_detection_is_unavailable(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            take_a_photo,
            "capture_best_photo",
            return_value=frame,
        ), patch.object(
            take_a_photo,
            "detect_person_YOLO",
            side_effect=FileNotFoundError("missing model"),
        ), patch.object(
            take_a_photo,
            "save_image_with_gps",
        ) as mock_save:
            success, photo_path = take_a_photo.take_photo(object(), 1.0, 2.0, tmpdir)

        self.assertFalse(success)
        self.assertIsNone(photo_path)
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
