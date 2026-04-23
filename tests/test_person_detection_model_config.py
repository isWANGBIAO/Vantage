import unittest
from pathlib import Path

from src import server
from src.services import person_detection


class PersonDetectionModelConfigTests(unittest.TestCase):
    def test_shared_model_constant_switches_to_yolo26m(self):
        self.assertEqual(person_detection.PERSON_DETECTION_MODEL, "yolo26m.pt")

    def test_server_uses_shared_model_constant(self):
        self.assertEqual(server.PERSON_DETECTION_MODEL, person_detection.PERSON_DETECTION_MODEL)

    def test_server_uses_shared_confidence_constant(self):
        self.assertEqual(
            server.PERSON_DETECTION_CONFIDENCE,
            person_detection.PERSON_DETECTION_CONFIDENCE,
        )

    def test_server_avoids_top_level_ultralytics_import(self):
        server_source = Path("src/server.py").read_text(encoding="utf-8")
        self.assertNotIn("from ultralytics import YOLO", server_source)


if __name__ == "__main__":
    unittest.main()
