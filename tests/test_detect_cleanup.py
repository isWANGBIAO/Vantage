import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src import detect
from src.manager.take_photo import take_a_photo


class DetectCleanupTests(unittest.TestCase):
    def test_format_duration_uses_seconds_under_one_minute(self):
        self.assertEqual(detect.format_duration(12.345), "12.35s")

    def test_format_duration_uses_minutes_over_one_minute(self):
        self.assertEqual(detect.format_duration(61.2), "1.02m")

    def test_build_progress_message_includes_speed_and_formatted_time(self):
        message = detect.build_progress_message(
            index=5,
            total_files=10,
            photos_with_people=3,
            photos_without_people=2,
            detection_rate=4.25,
            remaining_time=125.0,
            elapsed_time=30.0,
        )

        self.assertIn("speed: 4.25 img/s", message)
        self.assertIn("eta: 2.08m", message)
        self.assertIn("elapsed: 30.00s", message)

    def test_get_screenshots_within_time_range_only_scans_adjacent_hour_dirs(self):
        photo_time = datetime(2026, 3, 12, 12, 0, 1)
        screenshots_root = Path("C:/shots")
        scanned_dirs = []

        def fake_iter_image_files(root_dir):
            scanned_dirs.append(root_dir)
            return []

        with patch.object(detect, "iter_image_files", side_effect=fake_iter_image_files):
            detect.get_screenshots_within_time_range(
                photo_time,
                str(screenshots_root),
                time_range_seconds=2,
            )

        self.assertEqual(
            scanned_dirs,
            [
                str(screenshots_root / "2026" / "03" / "12" / "11"),
                str(screenshots_root / "2026" / "03" / "12" / "12"),
                str(screenshots_root / "2026" / "03" / "12" / "13"),
            ],
        )

    def test_emit_status_flushes_output(self):
        with patch("builtins.print") as mock_print:
            detect.emit_status("hello")

        mock_print.assert_called_once_with("hello", flush=True)

    def test_detect_reports_total_before_loading_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            photos_dir.mkdir()
            screenshots_dir.mkdir()
            (photos_dir / "photo_20260312_120000.jpg").write_bytes(b"x")

            with patch.object(detect, "emit_status") as mock_status, patch.object(
                detect, "get_yolo_model", side_effect=RuntimeError("stop after preflight")
            ):
                with self.assertRaisesRegex(RuntimeError, "stop after preflight"):
                    detect.detect(str(photos_dir), str(screenshots_dir), dry_run=True)

        self.assertTrue(
            any(
                call.args and str(call.args[0]).startswith("Found 1 photos. Starting recheck with model")
                for call in mock_status.call_args_list
            )
        )

    def test_history_recheck_uses_same_confidence_as_live_capture(self):
        self.assertEqual(
            detect.PERSON_DETECTION_CONFIDENCE,
            take_a_photo.PERSON_DETECTION_CONFIDENCE,
        )

    def test_resolve_storage_paths_prefers_existing_onedrive_picture_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            photos_dir = home / "OneDrive" / "Pictures" / "本机照片"
            screenshots_dir = home / "OneDrive" / "Pictures" / "Screenshots"
            photos_dir.mkdir(parents=True)
            screenshots_dir.mkdir(parents=True)

            actual_photos, actual_screenshots = detect.resolve_storage_paths(
                user_home=str(home),
                onedrive_env=None,
                ensure_exists=False,
            )

        self.assertEqual(actual_photos, str(photos_dir))
        self.assertEqual(actual_screenshots, str(screenshots_dir))

    def test_collect_cleanup_targets_matches_related_screenshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            photo_dir = photos_dir / "2026" / "03" / "12" / "12"
            shot_dir = screenshots_dir / "2026" / "03" / "12" / "12"
            photo_dir.mkdir(parents=True)
            shot_dir.mkdir(parents=True)

            target_photo = photo_dir / "photo_20260312_120000.jpg"
            keep_photo = photo_dir / "photo_20260312_120500.jpg"
            shot_match = shot_dir / "screenshot_20260312_120001_monitor_1.jpg"
            shot_far = shot_dir / "screenshot_20260312_120010_monitor_1.jpg"

            for path in [target_photo, keep_photo, shot_match, shot_far]:
                path.write_bytes(b"x")

            def fake_detect(path):
                return 0 if path == str(target_photo) else 1

            cleanup_plan = detect.collect_cleanup_targets(
                photos_dir=str(photos_dir),
                screenshots_dir=str(screenshots_dir),
                detect_person_fn=fake_detect,
                time_range_seconds=2,
            )

        self.assertEqual(len(cleanup_plan), 1)
        self.assertEqual(cleanup_plan[0]["photo_path"], str(target_photo))
        self.assertEqual(cleanup_plan[0]["screenshot_paths"], [str(shot_match)])

    def test_apply_cleanup_plan_deletes_photo_and_screenshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photo_path = root / "photo_20260312_120000.jpg"
            screenshot_path = root / "screenshot_20260312_120001_monitor_1.jpg"
            photo_path.write_bytes(b"photo")
            screenshot_path.write_bytes(b"shot")

            detect.apply_cleanup_plan(
                [
                    {
                        "photo_path": str(photo_path),
                        "screenshot_paths": [str(screenshot_path)],
                        "delete_paths": [str(photo_path), str(screenshot_path)],
                        "photo_time": datetime(2026, 3, 12, 12, 0, 0),
                    }
                ]
            )

            self.assertFalse(photo_path.exists())
            self.assertFalse(screenshot_path.exists())


if __name__ == "__main__":
    unittest.main()
