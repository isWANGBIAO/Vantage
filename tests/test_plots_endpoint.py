import asyncio
import unittest
from unittest.mock import patch

from src import server


class PlotRefreshEndpointTests(unittest.TestCase):
    def setUp(self):
        if hasattr(server, "_clear_plot_dashboard_cache"):
            server._clear_plot_dashboard_cache()

    def tearDown(self):
        if hasattr(server, "_clear_plot_dashboard_cache"):
            server._clear_plot_dashboard_cache()

    def test_refresh_plots_clears_dashboard_cache_without_matplotlib_export(self):
        with (
            patch.object(server, "_clear_plot_dashboard_cache") as clear_cache,
            patch.object(
                server.subprocess,
                "run",
                side_effect=AssertionError("Vantage UI refresh should not run plot.py"),
            ) as run_script,
        ):
            payload = asyncio.run(server.refresh_plots())

        self.assertEqual(payload, {"message": "Plot dashboard data cache cleared", "status": "ready"})
        clear_cache.assert_called_once()
        run_script.assert_not_called()

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
