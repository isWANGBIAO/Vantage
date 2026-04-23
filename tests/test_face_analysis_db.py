import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import face_analysis_db
from src.utils.face_analysis_db import (
    ensure_face_analysis_db,
    initialize_face_analysis_storage,
    load_face_analysis_records,
    load_face_progress_cache,
    load_face_report_cache,
    save_face_progress_cache,
    save_face_report_cache,
    upsert_face_analysis_record,
)


class FaceAnalysisDbTests(unittest.TestCase):
    def test_default_face_analysis_db_file_follows_config_history_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"

            with patch.object(face_analysis_db.Config, "get_history_dir", return_value=history_dir):
                resolved = face_analysis_db.get_face_analysis_db_file()
                created = ensure_face_analysis_db()

        self.assertEqual(resolved, history_dir / "face_analysis.db")
        self.assertEqual(created, history_dir / "face_analysis.db")

    def test_upsert_and_load_face_analysis_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "face_analysis.db"
            ensure_face_analysis_db(db_path)

            upsert_face_analysis_record(
                {
                    "path": "photo.jpg",
                    "datetime": "2026-03-12 10:00:00",
                    "timestamp": 1773280800.0,
                    "passed": True,
                    "score": 12.3,
                    "score_left": 11.0,
                    "score_right": 13.6,
                    "delta_e_left": 10.1,
                    "delta_e_right": 11.2,
                    "delta_l_left": 9.0,
                    "delta_l_right": 9.5,
                    "fail_reason": [],
                },
                db_path,
            )

            rows = load_face_analysis_records(db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "photo.jpg")
        self.assertTrue(rows[0]["passed"])
        self.assertEqual(rows[0]["fail_reason"], [])
        self.assertAlmostEqual(rows[0]["score"], 12.3)

    def test_initialize_storage_clears_old_algorithm_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "face_analysis.db"
            ensure_face_analysis_db(db_path)
            upsert_face_analysis_record(
                {
                    "path": "old-photo.jpg",
                    "datetime": "2026-03-11 10:00:00",
                    "timestamp": 1773194400.0,
                    "passed": True,
                    "score": 99.0,
                    "score_left": 99.0,
                    "score_right": 99.0,
                    "delta_e_left": 99.0,
                    "delta_e_right": 99.0,
                    "delta_l_left": 99.0,
                    "delta_l_right": 99.0,
                    "fail_reason": [],
                },
                db_path,
            )
            save_face_report_cache({"count": 1}, db_path)
            save_face_progress_cache({"status": "done"}, db_path)

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO face_analysis_meta (meta_key, meta_value)
                    VALUES (?, ?)
                    ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
                    """,
                    ("analysis_algorithm_version", "dark_circle_v1"),
                )
                conn.commit()
            finally:
                conn.close()

            initialize_face_analysis_storage(db_path, algorithm_version="dark_circle_v2")
            rows = load_face_analysis_records(db_path)
            report = load_face_report_cache(db_path)
            progress = load_face_progress_cache(db_path)

        self.assertEqual(rows, [])
        self.assertIsNone(report)
        self.assertIsNone(progress)

    def test_initialize_storage_migrates_v2_scores_in_place(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "face_analysis.db"
            ensure_face_analysis_db(db_path)
            upsert_face_analysis_record(
                {
                    "path": "valid-photo.jpg",
                    "datetime": "2026-03-11 10:00:00",
                    "timestamp": 1773194400.0,
                    "passed": True,
                    "score": 1.23,
                    "score_left": 1.0,
                    "score_right": 1.46,
                    "delta_e_left": 10.0,
                    "delta_e_right": 11.0,
                    "delta_l_left": 9.0,
                    "delta_l_right": 10.0,
                    "fail_reason": [],
                },
                db_path,
            )
            upsert_face_analysis_record(
                {
                    "path": "failed-photo.jpg",
                    "datetime": "2026-03-11 11:00:00",
                    "timestamp": 1773198000.0,
                    "passed": False,
                    "score": None,
                    "score_left": None,
                    "score_right": None,
                    "delta_e_left": None,
                    "delta_e_right": None,
                    "delta_l_left": None,
                    "delta_l_right": None,
                    "fail_reason": ["NoFace"],
                },
                db_path,
            )
            save_face_report_cache({"count": 1}, db_path)
            save_face_progress_cache({"status": "done"}, db_path)

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO face_analysis_meta (meta_key, meta_value)
                    VALUES (?, ?)
                    ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
                    """,
                    ("analysis_algorithm_version", "dark_circle_v2"),
                )
                conn.commit()
            finally:
                conn.close()

            initialize_face_analysis_storage(db_path)
            rows = load_face_analysis_records(db_path)
            report = load_face_report_cache(db_path)
            progress = load_face_progress_cache(db_path)

            conn = sqlite3.connect(db_path)
            try:
                version = conn.execute(
                    "SELECT meta_value FROM face_analysis_meta WHERE meta_key = ?",
                    ("analysis_algorithm_version",),
                ).fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(len(rows), 2)
        valid_row = next(row for row in rows if row["path"] == "valid-photo.jpg")
        failed_row = next(row for row in rows if row["path"] == "failed-photo.jpg")
        self.assertAlmostEqual(valid_row["score"], 12.3)
        self.assertAlmostEqual(valid_row["score_left"], 10.0)
        self.assertAlmostEqual(valid_row["score_right"], 14.6)
        self.assertIsNone(failed_row["score"])
        self.assertIsNone(report)
        self.assertIsNone(progress)
        self.assertEqual(version, "dark_circle_v3")

    def test_save_and_load_report_and_progress_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "face_analysis.db"
            ensure_face_analysis_db(db_path)

            save_face_report_cache({"count": 2}, db_path)
            save_face_progress_cache({"status": "analyzing", "percent": 50}, db_path)

            report = load_face_report_cache(db_path)
            progress = load_face_progress_cache(db_path)

        self.assertEqual(report["count"], 2)
        self.assertEqual(progress["status"], "analyzing")
        self.assertEqual(progress["percent"], 50)


if __name__ == "__main__":
    unittest.main()
