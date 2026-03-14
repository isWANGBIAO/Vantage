import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.scripts import analyze_face


class AnalyzeFaceCliProgressTests(unittest.TestCase):
    def test_run_analysis_wraps_pending_photos_with_tqdm(self):
        photos = [
            {"path": "photo_a.jpg", "date": None, "timestamp": 1},
            {"path": "photo_b.jpg", "date": None, "timestamp": 2},
        ]
        analyzed_records = [
            {"path": "photo_a.jpg", "passed": True, "score": 1.0},
            {"path": "photo_b.jpg", "passed": True, "score": 2.0},
        ]

        with tempfile.TemporaryDirectory() as tmpdir, \
            patch.object(analyze_face, "initialize_face_analysis_storage"), \
            patch.object(analyze_face, "MediaPipeFaceDetector"), \
            patch.object(analyze_face, "FaceParser"), \
            patch.object(analyze_face, "scan_photos", return_value=photos), \
            patch.object(analyze_face, "load_face_analysis_paths", return_value=set()), \
            patch.object(analyze_face, "update_progress"), \
            patch.object(analyze_face, "analyze_photo_file", side_effect=analyzed_records), \
            patch.object(analyze_face, "upsert_face_analysis_record"), \
            patch.object(analyze_face, "load_face_analysis_records", return_value=analyzed_records), \
            patch.object(analyze_face, "build_face_report", return_value={"count": 1}), \
            patch.object(analyze_face, "save_face_report_cache"), \
            patch("src.scripts.analyze_face.tqdm", create=True) as tqdm_mock:
            tqdm_mock.side_effect = lambda iterable, **kwargs: iterable

            analyze_face.run_analysis(
                search_paths=["photos"],
                model_path="model.onnx",
                db_file="face.db",
                output_dir=tmpdir,
            )

        tqdm_mock.assert_called_once()
        self.assertEqual(tqdm_mock.call_args.kwargs["total"], 2)
        self.assertEqual(tqdm_mock.call_args.kwargs["desc"], "Analyzing face photos")

    def test_run_analysis_skips_tqdm_when_no_photos_need_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
            patch.object(analyze_face, "initialize_face_analysis_storage"), \
            patch.object(analyze_face, "MediaPipeFaceDetector"), \
            patch.object(analyze_face, "FaceParser"), \
            patch.object(analyze_face, "scan_photos", return_value=[]), \
            patch.object(analyze_face, "load_face_analysis_paths", return_value=set()), \
            patch.object(analyze_face, "update_progress"), \
            patch.object(analyze_face, "load_face_analysis_records", return_value=[]), \
            patch.object(analyze_face, "build_face_report", return_value={"count": 0}), \
            patch.object(analyze_face, "clear_face_report_cache"), \
            patch("src.scripts.analyze_face.tqdm", create=True) as tqdm_mock:
            analyze_face.run_analysis(
                search_paths=["photos"],
                model_path="model.onnx",
                db_file="face.db",
                output_dir=tmpdir,
            )

        tqdm_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
