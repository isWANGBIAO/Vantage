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

    def test_shared_model_constant_uses_yunet(self):
        self.assertEqual(
            person_detection.PERSON_DETECTION_MODEL,
            "face_detection_yunet_2023mar.onnx",
        )

    def test_presence_uses_half_confidence_and_half_percent_area(self):
        self.assertEqual(person_detection.PRESENCE_DETECTION_CONFIDENCE, 0.50)
        self.assertEqual(person_detection.PRESENCE_MIN_FACE_AREA_RATIO, 0.005)

    def test_yolox_presence_api_is_removed(self):
        removed_names = (
            "PRESENCE_PERSON_DETECTION_MODEL",
            "PRESENCE_PERSON_DETECTION_CONFIDENCE",
            "PERSON_PRESENCE_MODEL_PATH_ENV",
            "resolve_person_presence_model_path",
            "get_person_presence_detector",
            "OpenCvYoloXPersonDetector",
        )

        for name in removed_names:
            with self.subTest(name=name):
                self.assertFalse(hasattr(person_detection, name))

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
                person_detection, "__file__", str(source_file)
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_pyinstaller_meipass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "src" / "models" / person_detection.PERSON_DETECTION_MODEL
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys, "_MEIPASS", tmpdir, create=True
            ):
                resolved = person_detection.resolve_face_detection_model_path()

        self.assertEqual(resolved, model_path.resolve())

    def test_model_path_resolves_pyinstaller_meipass_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / person_detection.PERSON_DETECTION_MODEL
            model_path.write_bytes(b"onnx")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                person_detection.sys, "_MEIPASS", tmpdir, create=True
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
                person_detection.sys, "executable", str(executable)
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
                person_detection.sys, "executable", str(executable)
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

    def test_sources_have_no_yolox_or_body_presence_runtime(self):
        for path in (Path("src/services/person_detection.py"), Path("src/server.py")):
            source = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=path):
                self.assertNotIn("yolox", source)
                self.assertNotIn("vantage_person_presence_model_path", source)
                self.assertNotIn("get_person_presence_detector", source)

    def test_server_and_detector_sources_do_not_import_heavy_inference_runtimes(self):
        server_source = Path("src/server.py").read_text(encoding="utf-8")
        detector_source = Path("src/services/person_detection.py").read_text(encoding="utf-8")

        combined_source = f"{server_source}\n{detector_source}".lower()
        self.assertNotIn("ultralytics", combined_source)
        self.assertNotIn("import torch", combined_source)
        self.assertNotIn("onnxruntime", combined_source)


if __name__ == "__main__":
    unittest.main()
