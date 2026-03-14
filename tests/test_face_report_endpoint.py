import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server
from src.utils.face_analysis_db import (
    initialize_face_analysis_storage,
    load_face_analysis_records,
    save_face_report_cache,
)
from src.utils.face_report_cache import load_face_report_cache


class FaceReportEndpointTests(unittest.TestCase):
    def test_cached_report_returns_without_running_subprocess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = Path(tmpdir) / "face_analysis.db"
            initialize_face_analysis_storage(db_path)
            save_face_report_cache(
                {
                    "heaviest": {
                        "path": str(tmp / "heaviest.jpg"),
                        "date": "2026-03-07 11:00:00",
                        "score": 9.8,
                    },
                    "lightest": {
                        "path": str(tmp / "lightest.jpg"),
                        "date": "2026-03-06 11:00:00",
                        "score": 2.1,
                    },
                    "trend_plot_path": str(tmp / "dark_circles_trend.png"),
                    "trend_views": {
                        "day": {
                            "label": "最近24小时",
                            "points": [{"timestamp": 1, "datetime": "2026-03-07 11:00:00", "score": 9.8}],
                        },
                        "week": {
                            "label": "最近7天",
                            "points": [{"timestamp": 1, "datetime": "2026-03-07 00:00:00", "score": 9.8}],
                        },
                        "month": {
                            "label": "最近30天",
                            "points": [{"timestamp": 1, "datetime": "2026-03-07 00:00:00", "score": 9.8}],
                        },
                        "all": {
                            "label": "全部历史",
                            "points": [{"timestamp": 1, "datetime": "2026-03-07 00:00:00", "score": 9.8}],
                        },
                    },
                },
                db_path,
            )

            with patch.object(server, "FACE_ANALYSIS_DB_FILE", db_path), patch.object(
                server.asyncio, "to_thread", side_effect=AssertionError("GET /api/face/report should not trigger background analysis")
            ):
                payload = asyncio.run(server.get_face_report())

        self.assertEqual(payload["heaviest"]["score"], 9.8)
        self.assertIn("/api/image_proxy", payload["heaviest"]["url"])
        self.assertIn("dark_circles_trend.png", payload["trend_plot"])
        self.assertEqual(set(payload["trend_views"].keys()), {"day", "week", "month", "all"})
        self.assertEqual(payload["trend_views"]["all"]["points"][0]["score"], 9.8)

    def test_cached_report_without_trend_views_returns_empty_trend_groups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = Path(tmpdir) / "face_analysis.db"
            initialize_face_analysis_storage(db_path)
            save_face_report_cache(
                {
                    "heaviest": {
                        "path": str(tmp / "heaviest.jpg"),
                        "date": "2026-03-07 11:00:00",
                        "score": 9.8,
                    },
                    "lightest": {
                        "path": str(tmp / "lightest.jpg"),
                        "date": "2026-03-06 11:00:00",
                        "score": 2.1,
                    },
                    "trend_plot_path": str(tmp / "dark_circles_trend.png"),
                },
                db_path,
            )

            with patch.object(server, "FACE_ANALYSIS_DB_FILE", db_path):
                payload = asyncio.run(server.get_face_report())

        self.assertEqual(payload["trend_views"]["day"]["points"], [])
        self.assertEqual(payload["trend_views"]["week"]["points"], [])
        self.assertEqual(payload["trend_views"]["month"]["points"], [])
        self.assertEqual(payload["trend_views"]["all"]["points"], [])

    def test_missing_cache_returns_empty_state_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing.db"
            with patch.object(server, "FACE_ANALYSIS_DB_FILE", db_path):
                payload = asyncio.run(server.get_face_report())

        self.assertEqual(payload["error"], "No report generated")

    def test_process_captured_face_photo_writes_record_and_refreshes_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "face_analysis.db"
            output_dir = tmp / "plots"
            photo_path = tmp / "photo_20260314_210000.jpg"
            photo_path.write_bytes(b"fake")
            initialize_face_analysis_storage(db_path)

            fake_record = {
                "path": str(photo_path),
                "datetime": "2026-03-14 21:00:00",
                "timestamp": 1773493200.0,
                "passed": True,
                "score": 30.5,
                "score_left": 30.0,
                "score_right": 31.0,
                "delta_e_left": 28.0,
                "delta_e_right": 29.0,
                "delta_l_left": 12.0,
                "delta_l_right": 13.0,
                "fail_reason": [],
            }
            fake_report = {
                "count": 1,
                "heaviest": {"path": str(photo_path), "date": "2026-03-14 21:00:00", "score": 30.5},
                "lightest": {"path": str(photo_path), "date": "2026-03-14 21:00:00", "score": 30.5},
                "trend_plot_path": str(output_dir / "dark_circles_trend.png"),
                "trend_views": {
                    "day": {"label": "最近24小时", "points": [{"timestamp": 1773493200.0, "datetime": "2026-03-14 21:00:00", "score": 30.5}]},
                    "week": {"label": "最近7天", "points": []},
                    "month": {"label": "最近30天", "points": []},
                    "all": {"label": "全部历史", "points": [{"timestamp": 1773493200.0, "datetime": "2026-03-14 21:00:00", "score": 30.5}]},
                },
            }

            with patch.object(server, "FACE_ANALYSIS_DB_FILE", db_path), patch.object(
                server, "FACE_REPORT_PLOT_OUTPUT_DIR", output_dir
            ), patch.object(
                server, "get_face_analysis_runtime", return_value=(object(), object(), object())
            ), patch.object(server, "analyze_photo_file", return_value=fake_record), patch.object(
                server, "build_face_report", return_value=fake_report
            ):
                server.process_captured_face_photo(str(photo_path))

            rows = load_face_analysis_records(db_path)
            cached = load_face_report_cache(db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], str(photo_path))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["count"], 1)


if __name__ == "__main__":
    unittest.main()
