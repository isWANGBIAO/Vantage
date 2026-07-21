import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

from src import server
from src.core.media_storage import get_media_paths_settings_file, save_media_paths_settings
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
            server,
            "get_trusted_location_async",
            return_value=(31.2304, 121.4737),
        ) as mock_location, patch.object(
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
        mock_location.assert_awaited_once()

    def test_identify_logs_folder_prefers_d_drive_over_user_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config_dir = tmp / "config"
            fake_d_root = tmp / "portable_d"
            photos_dir = fake_d_root / "Pictures" / "本机照片"
            screenshots_dir = fake_d_root / "Pictures" / "Screenshots"
            photos_dir.mkdir(parents=True)
            screenshots_dir.mkdir(parents=True)

            actual_photos, actual_screenshots = server.identify_logs_folder(
                config_dir=config_dir,
                user_home=str(tmp / "home"),
                onedrive_env=None,
                onedrive_consumer_env=None,
                d_drive_root=str(fake_d_root),
            )
            payload = json.loads(
                get_media_paths_settings_file(config_dir=config_dir).read_text(encoding="utf-8")
            )

        self.assertEqual(actual_photos, str(photos_dir))
        self.assertEqual(actual_screenshots, str(screenshots_dir))
        self.assertEqual(payload["photos_path"], str(photos_dir))
        self.assertEqual(payload["screenshots_path"], str(screenshots_dir))

    def test_identify_logs_folder_reuses_saved_media_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config_dir = tmp / "config"
            saved_root = tmp / "saved_root"
            saved_photos = saved_root / "Pictures" / "本机照片"
            saved_screenshots = saved_root / "Pictures" / "Screenshots"
            saved_photos.mkdir(parents=True)
            saved_screenshots.mkdir(parents=True)

            save_media_paths_settings(
                saved_photos,
                saved_screenshots,
                settings_file=get_media_paths_settings_file(config_dir=config_dir),
            )

            newer_root = tmp / "newer_root"
            (newer_root / "Pictures" / "本机照片").mkdir(parents=True)
            (newer_root / "Pictures" / "Screenshots").mkdir(parents=True)

            actual_photos, actual_screenshots = server.identify_logs_folder(
                config_dir=config_dir,
                user_home=str(tmp / "home"),
                onedrive_env=None,
                onedrive_consumer_env=None,
                d_drive_root=str(newer_root),
            )

        self.assertEqual(actual_photos, str(saved_photos))
        self.assertEqual(actual_screenshots, str(saved_screenshots))

    def test_startup_event_schedules_latest_media_scan_in_background(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            photos_dir = tmp / "photos"
            screenshots_dir = tmp / "screenshots"
            plot_dir = tmp / "plot_outputs"
            photos_dir.mkdir(parents=True)
            screenshots_dir.mkdir(parents=True)

            started_threads = []
            original_paths = dict(server.state.paths)
            original_status = dict(server.state.background_thread_status)
            original_monitor = server.state.monitor
            original_photos_path = server.state.photos_path
            original_screenshots_path = server.state.screenshots_path
            original_running = server.state.is_running

            try:
                with patch.object(
                    server,
                    "identify_logs_folder",
                    return_value=(str(photos_dir), str(screenshots_dir)),
                ), patch.object(
                    server,
                    "Monitor",
                    return_value=object(),
                ), patch.object(
                    server,
                    "_mount_static_once",
                    return_value=False,
                ), patch.object(
                    server,
                    "_get_plot_dir",
                    return_value=plot_dir,
                ), patch.object(
                    server,
                    "_start_background_thread_once",
                    side_effect=lambda name, target: started_threads.append(name) or True,
                ), patch.object(
                    server,
                    "find_latest_file_recursive",
                    side_effect=AssertionError("startup should not scan latest files synchronously"),
                ):
                    asyncio.run(server.startup_event())
            finally:
                server.state.paths = original_paths
                server.state.background_thread_status = original_status
                server.state.monitor = original_monitor
                server.state.photos_path = original_photos_path
                server.state.screenshots_path = original_screenshots_path
                server.state.is_running = original_running

        self.assertIn("initialize_latest_media_state", started_threads)

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

    def test_data_loader_resolve_data_root_finds_macos_cloudstorage_onedrive_mine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            (home / "OneDrive").mkdir()
            data_root = home / "Library" / "CloudStorage" / "OneDrive-Personal" / "Mine"
            data_root.mkdir(parents=True)

            with patch.dict(os.environ, {}, clear=True):
                resolved = DataLoader.resolve_data_root(user_home=str(home), onedrive_env=None)

        self.assertEqual(resolved, data_root)

    def test_data_loader_resolve_data_path_finds_macos_cloudstorage_workbook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            (home / "OneDrive").mkdir()
            data_root = home / "Library" / "CloudStorage" / "OneDrive-Personal" / "Mine"
            data_root.mkdir(parents=True)
            workbook = data_root / "Time.xlsx"
            workbook.write_bytes(b"fake")

            with patch.dict(os.environ, {}, clear=True):
                resolved = DataLoader.resolve_data_path("Time.xlsx", user_home=str(home), onedrive_env=None)

        self.assertEqual(resolved, workbook)

    def test_data_loader_resolve_health_data_root_prefers_dated_english_health_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            archive_root = home / "OneDrive" / "Mine" / "20260416 MiFitness Zepp health history data"
            (archive_root / "mi_fiteness_data").mkdir(parents=True)

            with patch.dict(os.environ, {}, clear=True):
                resolved = DataLoader.resolve_health_data_root(
                    "mi_fiteness_data",
                    user_home=str(home),
                    onedrive_env=None,
                )

        self.assertEqual(resolved, archive_root)

    def test_plot_running_data_root_uses_health_archive_resolver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_root = Path(tmpdir)

            with patch.object(plot.DataLoader, "resolve_health_data_root", return_value=archive_root) as mock_resolve:
                resolved = plot._resolve_running_data_root()

        self.assertEqual(resolved, archive_root)
        mock_resolve.assert_called_once_with()

    def test_plot_running_loaders_find_mi_and_zepp_in_separate_archives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mine_root = Path(tmpdir) / "OneDrive" / "Mine"
            mi_root = mine_root / "20260416 MiFitness health history data"
            zepp_root = mine_root / "20260417 Zepp health history data"
            mi_dir = mi_root / "mi_fiteness_data"
            zepp_dir = zepp_root / "zepplift_data" / "SPORT"
            mi_dir.mkdir(parents=True)
            zepp_dir.mkdir(parents=True)

            mi_csv = mi_dir / "20260416_881116692_MiFitness_hlth_center_sport_record.csv"
            mi_csv.write_text(
                'Category,Value,Time\n'
                '"running","{""start_time"":1782748800,""distance"":5000,""duration"":1800}",1782748800\n',
                encoding="utf-8",
            )
            (zepp_dir / "SPORT_running_master.csv").write_text(
                "summary_start_local,distance_km,duration_seconds,avg_pace_min_per_km\n"
                "2026-06-29 08:00:00,3.2,1200,6.25\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True), patch.object(
                plot.DataLoader,
                "_data_root_candidates",
                return_value=[mine_root],
            ):
                combined = plot.load_app_running_log_frame()

        self.assertEqual(len(combined), 2)
        source_text = "\n".join(combined["运动"].astype(str).tolist())
        self.assertIn("Mi Fitness 跑步", source_text)
        self.assertIn("Zepp 跑步", source_text)

    def test_plot_running_explicit_data_dir_bypasses_health_archive_resolver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            mi_dir = data_root / "mi_fiteness_data"
            mi_dir.mkdir(parents=True)
            (mi_dir / "20260416_881116692_MiFitness_hlth_center_sport_record.csv").write_text(
                'Category,Value,Time\n'
                '"running","{""start_time"":1782748800,""distance"":5000,""duration"":1800}",1782748800\n',
                encoding="utf-8",
            )

            with patch.object(
                plot.DataLoader,
                "resolve_health_data_root",
                side_effect=AssertionError("explicit data_dir should not use archive resolver"),
            ):
                frame = plot.load_mi_fitness_running_log_frame(data_dir=data_root)

        self.assertEqual(len(frame), 1)
        self.assertIn("Mi Fitness 跑步", frame.iloc[0]["运动"])

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
