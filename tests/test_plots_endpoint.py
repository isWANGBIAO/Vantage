import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server


class PlotRefreshEndpointTests(unittest.TestCase):
    def setUp(self):
        if hasattr(server, "_clear_plot_dashboard_cache"):
            server._clear_plot_dashboard_cache()

    def tearDown(self):
        if hasattr(server, "_clear_plot_dashboard_cache"):
            server._clear_plot_dashboard_cache()

    def test_refresh_plots_runs_script_before_returning(self):
        calls = []
        script_path = Path(server.__file__).resolve().parent / "scripts" / "plot.py"

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))

        with (
            patch.object(server.os.path, "exists", return_value=True),
            patch.object(server.subprocess, "run", side_effect=fake_run),
            patch.object(server, "_get_runtime_workdir", return_value=Path("C:/runtime")),
        ):
            payload = asyncio.run(server.refresh_plots())

        self.assertEqual(payload, {"message": "Plots refreshed successfully"})
        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(command, [sys.executable, str(script_path), "--dark"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(Path(kwargs["cwd"]), Path("C:/runtime"))
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(kwargs["timeout"], server.PLOT_REFRESH_TIMEOUT_SECONDS)

    def test_refresh_plots_rejects_concurrent_refresh(self):
        acquired = server._plot_refresh_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            response = asyncio.run(server.refresh_plots())
        finally:
            server._plot_refresh_lock.release()

        self.assertEqual(response.status_code, 409)

    def test_plot_dashboard_data_reuses_cache_for_unchanged_sources(self):
        calls = []

        async def fake_to_thread(func, *args, **kwargs):
            calls.append(func)
            return {"charts": [], "count": len(calls)}

        with patch.object(server, "_get_plot_dashboard_cache_key", return_value=(("Time.xlsx", 1, 1),)), patch.object(
            server.asyncio,
            "to_thread",
            side_effect=fake_to_thread,
        ):
            first = asyncio.run(server.get_plot_dashboard_data())
            second = asyncio.run(server.get_plot_dashboard_data())

        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 1)
        self.assertEqual(len(calls), 1)

    def test_plot_dashboard_data_rebuilds_when_source_signature_changes(self):
        calls = []

        async def fake_to_thread(func, *args, **kwargs):
            calls.append(func)
            return {"charts": [], "count": len(calls)}

        with patch.object(
            server,
            "_get_plot_dashboard_cache_key",
            side_effect=[(("Time.xlsx", 1, 1),), (("Time.xlsx", 2, 1),)],
        ), patch.object(
            server.asyncio,
            "to_thread",
            side_effect=fake_to_thread,
        ):
            first = asyncio.run(server.get_plot_dashboard_data())
            second = asyncio.run(server.get_plot_dashboard_data())

        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 2)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
