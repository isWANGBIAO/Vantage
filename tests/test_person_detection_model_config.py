import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import server
from src.services import person_detection


class PersonDetectionModelConfigTests(unittest.TestCase):
    def tearDown(self):
        person_detection._FACE_DETECTOR = None

    def test_shared_model_constant_switches_to_yunet(self):
        self.assertEqual(
            person_detection.PERSON_DETECTION_MODEL,
            "face_detection_yunet_2023mar.onnx",
        )

    def test_server_uses_shared_model_and_confidence_constants(self):
        self.assertEqual(server.PERSON_DETECTION_MODEL, person_detection.PERSON_DETECTION_MODEL)
        self.assertEqual(
            server.PERSON_DETECTION_CONFIDENCE,
            person_detection.PERSON_DETECTION_CONFIDENCE,
        )

    def test_model_path_prefers_environment_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "custom-yunet.onnx"
            model_path.write_bytes(b"onnx")

            with patch.dict(
                os.environ,
                {person_detection.FACE_DETECTION_MODEL_PATH_ENV: str(model_path)},
                clear=True,
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_source_src_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "src" / "services" / "person_detection.py"
            model_path = Path(tmpdir) / "src" / "models" / person_detection.PERSON_DETECTION_MODEL
            source_file.parent.mkdir(parents=True)
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection,
                "__file__",
                str(source_file),
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_pyinstaller_meipass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "src" / "models" / person_detection.PERSON_DETECTION_MODEL
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys,
                "_MEIPASS",
                tmpdir,
                create=True,
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_pyinstaller_meipass_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / person_detection.PERSON_DETECTION_MODEL
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys,
                "_MEIPASS",
                tmpdir,
                create=True,
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_executable_internal_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "VantageBackend.exe"
            model_path = (
                Path(tmpdir)
                / "_internal"
                / "src"
                / "models"
                / person_detection.PERSON_DETECTION_MODEL
            )
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys,
                "executable",
                str(executable),
            ), patch.object(
                person_detection,
                "__file__",
                str(Path(tmpdir) / "missing" / "services" / "person_detection.py"),
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_executable_internal_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "VantageBackend.exe"
            model_path = Path(tmpdir) / "_internal" / person_detection.PERSON_DETECTION_MODEL
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys,
                "executable",
                str(executable),
            ), patch.object(
                person_detection,
                "__file__",
                str(Path(tmpdir) / "missing" / "services" / "person_detection.py"),
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_face_detector_factory_loads_yunet_once(self):
        detector = object()
        factory = Mock(return_value=detector)
        fake_cv2 = types.SimpleNamespace(FaceDetectorYN_create=factory)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / person_detection.PERSON_DETECTION_MODEL
            model_path.write_bytes(b"onnx")
            with patch.dict(sys.modules, {"cv2": fake_cv2}), patch.object(
                person_detection,
                "resolve_face_detection_model_path",
                return_value=model_path,
            ):
                first = person_detection.get_face_detector()
                second = person_detection.get_face_detector()

        self.assertIs(first, detector)
        self.assertIs(second, detector)
        factory.assert_called_once_with(
            str(model_path),
            "",
            person_detection.FACE_DETECTION_INPUT_SIZE,
            person_detection.PERSON_DETECTION_CONFIDENCE,
            person_detection.FACE_DETECTION_NMS_THRESHOLD,
            person_detection.FACE_DETECTION_TOP_K,
        )

    def test_server_and_detector_sources_do_not_import_ultralytics_or_log_yolo(self):
        server_source = Path("src/server.py").read_text(encoding="utf-8")
        detector_source = Path("src/services/person_detection.py").read_text(encoding="utf-8")

        self.assertNotIn("ultralytics", server_source.lower())
        self.assertNotIn("ultralytics", detector_source.lower())
        self.assertNotIn("yolo", server_source.lower())
        self.assertNotIn("yolo", detector_source.lower())


if __name__ == "__main__":
    unittest.main()
