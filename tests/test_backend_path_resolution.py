import asyncio
import importlib.util
import os
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

from src import server
from src.scripts import plot
from src.utils.data_loader import DataLoader

jieba_stub = types.ModuleType("jieba")
jieba_stub.cut = lambda text, cut_all=False: list(text)
sys.modules.setdefault("jieba", jieba_stub)

from src.AI_Prediction import analyzer


class BackendPathResolutionTests(unittest.TestCase):
    def test_plot_script_ensures_project_root_on_sys_path_when_run_directly(self):
        module_path = Path("src/scripts/plot.py")
        spec = importlib.util.spec_from_file_location("plot_script_under_test", module_path)
        plot_script = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(plot_script)

        repo_root = plot_script._ensure_project_root_on_sys_path(
            script_path=module_path.resolve(),
            path_list=[],
        )

        self.assertEqual(repo_root, module_path.resolve().parents[2])

    def test_server_runtime_helpers_use_config_runtime_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            runtime_logs = tmp_path / "appdata" / "logs"
            runtime_plots = tmp_path / "appdata" / "plot_outputs"
            runtime_history = tmp_path / "appdata" / "history"
            project_root = tmp_path / "repo"

            with patch.object(server.Config, "get_logs_dir", return_value=runtime_logs), patch.object(
                server.Config,
                "get_plot_dir",
                return_value=runtime_plots,
            ), patch.object(
                server.Config,
                "get_history_dir",
                return_value=runtime_history,
            ), patch.object(
                server.Config,
                "get_project_root",
                return_value=project_root,
            ):
                self.assertEqual(server._runtime_logs_root(), runtime_logs)
                self.assertEqual(server._get_plot_dir(), runtime_plots)
                self.assertEqual(server._get_history_dir(), str(runtime_history))
                self.assertEqual(server._get_runtime_workdir(), project_root)

    def test_aqi_endpoint_degrades_when_upstream_times_out(self):
        with patch.object(
            server.asyncio,
            "to_thread",
            side_effect=TimeoutError("boom"),
        ):
            response = asyncio.run(server.get_aqi_stats())

        self.assertIsInstance(response, dict)
        payload = response
        self.assertIsNone(payload["aqi"])
        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("error", payload)

    def test_identify_logs_folder_prefers_d_drive_over_user_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            photos_dir = Path(r"D:\\WANGBIAO\\Pictures\\本机照片")
            screenshots_dir = Path(r"D:\\WANGBIAO\\Pictures\\Screenshots")

            def fake_exists(path):
                path_str = str(path)
                if path_str.startswith(r"D:\WANGBIAO"):
                    return True
                return Path(path_str).exists()

            with patch.object(server.os.path, "expanduser", return_value=str(home)), patch.object(
                server.os.path, "exists", side_effect=fake_exists
            ), patch.object(server.os, "makedirs", return_value=None), patch.dict(os.environ, {}, clear=True):
                actual_photos, actual_screenshots = server.identify_logs_folder()

        self.assertEqual(actual_photos, str(photos_dir))
        self.assertEqual(actual_screenshots, str(screenshots_dir))

    def test_data_loader_resolve_data_root_prefers_user_one_drive_mine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            data_root = home / "OneDrive" / "Mine"
            data_root.mkdir(parents=True)

            with patch.dict(os.environ, {}, clear=True):
                resolved = DataLoader.resolve_data_root(user_home=str(home), onedrive_env=None)

        self.assertEqual(resolved, data_root)

    def test_data_loader_resolve_data_root_prefers_explicit_onedrive_mine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            one_drive = home / "CustomOneDrive"
            data_root = one_drive / "Mine"
            data_root.mkdir(parents=True)

            with patch.dict(os.environ, {}, clear=True):
                resolved = DataLoader.resolve_data_root(user_home=str(home), onedrive_env=str(one_drive))

        self.assertEqual(resolved, data_root)

    def test_analyzer_uses_resolved_time_sheet_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            time_xlsx = tmp / "Time.xlsx"
            time_xlsx.write_bytes(b"fake")

            fake_df = analyzer.pd.DataFrame(
                {
                    "日期": ["2026-03-26", "2026-03-27"],
                    "生活（饮食+社交+运动）": ["a", "b"],
                    "健康情况": ["", "ok"],
                }
            )

            with patch.object(analyzer.DataLoader, "resolve_data_path", return_value=time_xlsx) as mock_resolve, patch.object(
                analyzer.pd,
                "read_excel",
                return_value=fake_df,
            ) as mock_read, patch.object(analyzer.pd.DataFrame, "to_csv", autospec=True) as mock_to_csv:
                result = analyzer.read_and_preprocess_data()

        self.assertEqual(len(result), 2)
        mock_resolve.assert_called_once_with("Time.xlsx")
        mock_read.assert_called_once_with(time_xlsx)
        mock_to_csv.assert_called_once()

    def test_plot_resolve_data_root_delegates_to_data_loader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.object(plot.DataLoader, "resolve_data_root", return_value=tmp) as mock_resolve:
                resolved = plot.resolve_data_root()

        self.assertEqual(resolved, tmp)
        mock_resolve.assert_called_once()


if __name__ == "__main__":
    unittest.main()


