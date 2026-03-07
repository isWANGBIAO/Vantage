import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server
from src.utils.face_report_cache import save_face_report_cache


class FaceReportEndpointTests(unittest.TestCase):
    def test_cached_report_returns_without_running_subprocess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "face_report.json"
            save_face_report_cache(
                {
                    "heaviest": {
                        "path": str(Path(tmpdir) / "heaviest.jpg"),
                        "date": "2026-03-07 11:00:00",
                        "score": 9.8,
                    },
                    "lightest": {
                        "path": str(Path(tmpdir) / "lightest.jpg"),
                        "date": "2026-03-06 11:00:00",
                        "score": 2.1,
                    },
                    "trend_plot_path": str(Path(tmpdir) / "dark_circles_trend.png"),
                },
                report_path,
            )

            with patch.object(server, "FACE_REPORT_CACHE_FILE", report_path), patch.object(
                server.asyncio,
                "to_thread",
                side_effect=AssertionError("GET /api/face/report should not trigger background analysis"),
            ):
                payload = asyncio.run(server.get_face_report())

        self.assertEqual(payload["heaviest"]["score"], 9.8)
        self.assertIn("/api/image_proxy", payload["heaviest"]["url"])
        self.assertIn("dark_circles_trend.png", payload["trend_plot"])

    def test_missing_cache_returns_empty_state_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "missing.json"
            with patch.object(server, "FACE_REPORT_CACHE_FILE", report_path):
                payload = asyncio.run(server.get_face_report())

        self.assertEqual(payload["error"], "No report generated")


if __name__ == "__main__":
    unittest.main()
