import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks

from src import server
from src.utils.face_analysis_db import (
    initialize_face_analysis_storage,
    load_face_analysis_records,
    save_face_progress_cache,
    save_face_report_cache,
)
from src.utils.face_report_cache import load_face_report_cache


class FaceReportEndpointTests(unittest.TestCase):
    def test_face_analysis_background_task_writes_to_dedicated_runtime_log(self):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 4, 20, 22, 15, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            background_tasks = BackgroundTasks()
            logs_dir = tmp / "logs"

            with patch.object(server.Config, "get_logs_dir", return_value=logs_dir), patch.object(
                server,
                "datetime",
                FrozenDateTime,
            ), patch.object(server.subprocess, "run") as mock_run:
                payload = asyncio.run(server.analyze_face_history(background_tasks))
                self.assertEqual(payload["message"], "Analysis started in background")
                self.assertEqual(len(background_tasks.tasks), 1)
                task = background_tasks.tasks[0]
                task.func(*task.args, **task.kwargs)
                latest_pointer_content = (tmp / "logs" / "face-analysis.latest.log").read_text(encoding="utf-8")

                stdout_handle = mock_run.call_args.kwargs["stdout"]
                stderr_handle = mock_run.call_args.kwargs["stderr"]
                self.assertTrue(stdout_handle.closed)
                self.assertEqual(stderr_handle, server.subprocess.STDOUT)
                self.assertEqual(
                    Path(latest_pointer_content),
                    tmp / "logs" / "face-analysis" / "face-analysis-20260420_221530.log",
                )
                self.assertEqual(
                    latest_pointer_content,
                    str((tmp / "logs" / "face-analysis" / "face-analysis-20260420_221530.log").resolve()),
                )

    def test_face_analysis_background_log_redacts_split_native_child_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            scripts_dir = tmp / "scripts"
            scripts_dir.mkdir()
            private_history = tmp / "Private History"
            private_history.mkdir()
            private_photo = private_history / "face-secret.jpg"
            secret = "face-analysis-bearer-secret-1234567890"
            script_path = scripts_dir / "analyze_face.py"
            script_path.write_text(
                "\n".join(
                    (
                        "import os",
                        f"private_path = {str(private_photo)!r}.encode('utf-8')",
                        f"secret = {secret!r}.encode('utf-8')",
                        "path_split = max(1, len(private_path) // 2)",
                        "os.write(1, b'search_paths=[' + private_path[:path_split])",
                        "os.write(1, private_path[path_split:] + b']\\n')",
                        "os.write(2, b'Authorization: Bea')",
                        "os.write(2, b'rer ' + secret + b'\\n')",
                    )
                ),
                encoding="utf-8",
            )
            runtime_paths = {
                "app_mode": "development",
                "data_dir": tmp / "data",
                "config_dir": tmp / "config",
                "history_dir": private_history,
                "log_dir": tmp / "logs",
                "plot_dir": tmp / "plots",
                "cache_dir": tmp / "cache",
                "runtime_dir": tmp / "runtime",
                "migration_dir": tmp / "migration",
            }
            background_tasks = BackgroundTasks()

            try:
                with (
                    patch.object(server, "__file__", str(tmp / "server.py")),
                    patch.object(server.Config, "get_project_root", return_value=tmp),
                    patch.object(server.Config, "get_runtime_paths", return_value=runtime_paths),
                    patch.object(server.Config, "get_logs_dir", return_value=runtime_paths["log_dir"]),
                ):
                    payload = asyncio.run(server.analyze_face_history(background_tasks))
                    self.assertEqual(payload["message"], "Analysis started in background")
                    task = background_tasks.tasks[0]
                    task.func(*task.args, **task.kwargs)

                latest = (runtime_paths["log_dir"] / "face-analysis.latest.log").read_text(
                    encoding="utf-8"
                )
                persisted = Path(latest).read_text(encoding="utf-8")
            finally:
                with server._face_analysis_job_lock:
                    server._face_analysis_job_running = False

            self.assertNotIn(str(private_history), persisted)
            self.assertNotIn(secret, persisted)
            self.assertIn("<HISTORY_DIR>", persisted)
            self.assertIn("Authorization: Bearer [REDACTED_TOKEN]", persisted)
            self.assertIn("face-secret.jpg", persisted)

    def test_face_analysis_rejects_duplicate_background_start(self):
        background_tasks = BackgroundTasks()

        try:
            first_payload = asyncio.run(server.analyze_face_history(background_tasks))
            second_response = asyncio.run(server.analyze_face_history(background_tasks))

            self.assertEqual(first_payload["message"], "Analysis started in background")
            self.assertEqual(second_response.status_code, 409)
            payload = json.loads(second_response.body.decode("utf-8"))
            self.assertEqual(payload["status"], "running")
            self.assertEqual(len(background_tasks.tasks), 1)
        finally:
            if hasattr(server, "_face_analysis_job_running"):
                with server._face_analysis_job_lock:
                    server._face_analysis_job_running = False

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

    def test_stale_progress_stays_running_when_background_job_is_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "face_analysis.db"
            initialize_face_analysis_storage(db_path)
            save_face_progress_cache({"status": "running", "percent": 42, "timestamp": 100}, db_path)

            try:
                with server._face_analysis_job_lock:
                    server._face_analysis_job_running = True

                with patch.object(server, "FACE_ANALYSIS_DB_FILE", db_path), patch.object(server.time, "time", return_value=200):
                    payload = asyncio.run(server.get_face_progress())
            finally:
                with server._face_analysis_job_lock:
                    server._face_analysis_job_running = False

        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["percent"], 42)
        self.assertTrue(payload["stale"])

    def test_export_face_excel_returns_text_details_when_export_path_is_missing(self):
        proc = SimpleNamespace(returncode=0, stdout=b"no export path\n", stderr=b"")

        with (
            patch.object(server.subprocess, "run", return_value=proc),
            patch.object(server, "_get_runtime_workdir", return_value=Path("C:/runtime")),
        ):
            response = asyncio.run(server.export_face_excel())

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "Export failed")
        self.assertEqual(payload["details"], "no export path\n")

    def test_export_face_excel_runs_subprocess_off_event_loop(self):
        proc = SimpleNamespace(returncode=0, stdout=b"EXPORT_PATH:C:/runtime/face.xlsx\n", stderr=b"")
        to_thread_calls = []

        async def fake_to_thread(func):
            to_thread_calls.append(func)
            return proc

        with (
            patch.object(server.asyncio, "to_thread", side_effect=fake_to_thread),
            patch.object(server.subprocess, "run", return_value=proc),
            patch.object(server.os.path, "exists", return_value=True),
            patch.object(server, "FileResponse", side_effect=lambda path, **kwargs: {"path": path, **kwargs}),
        ):
            response = asyncio.run(server.export_face_excel())

        self.assertEqual(len(to_thread_calls), 1)
        self.assertEqual(response["path"], "C:/runtime/face.xlsx")

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
            ), patch.object(
                server,
                "get_face_analysis_pipeline_module",
                return_value=SimpleNamespace(
                    analyze_photo_file=lambda *args, **kwargs: fake_record,
                    build_face_report=lambda *args, **kwargs: fake_report,
                ),
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
