import unittest
from unittest.mock import patch

from src.services import person_detection


class PersonDetectionTests(unittest.TestCase):
    def test_macos_uses_opencv_face_presence_detector_without_yolo(self):
        with patch.object(person_detection.sys, "platform", "darwin"), patch.object(
            person_detection,
            "detect_face_count_with_opencv",
            return_value=1,
        ) as face_detector, patch.object(
            person_detection,
            "get_yolo_model",
            side_effect=AssertionError("macOS should not require YOLO for presence detection"),
        ):
            self.assertEqual(person_detection.detect_person_count(object()), 1)

        face_detector.assert_called_once()

    def test_explicit_model_still_uses_yolo_result_counting(self):
        class FakeBox:
            cls = [person_detection.PERSON_CLASS_ID]

        class FakeResult:
            boxes = [FakeBox(), FakeBox()]

        class FakeModel:
            def predict(self, source, verbose, conf):
                return [FakeResult() for _ in source]

        with patch.object(person_detection.sys, "platform", "darwin"), patch.object(
            person_detection,
            "detect_face_count_with_opencv",
            side_effect=AssertionError("explicit model should bypass macOS face detector"),
        ):
            self.assertEqual(person_detection.detect_person_count(object(), model=FakeModel()), 2)


if __name__ == "__main__":
    unittest.main()
