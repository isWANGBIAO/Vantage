import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server


class PlotRefreshEndpointTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
