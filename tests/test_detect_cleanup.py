import tempfile
import unittest
import csv
import json
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

    def test_detect_skips_unreadable_photo_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            photos_dir.mkdir()
            screenshots_dir.mkdir()

            bad_photo = photos_dir / "photo_20260312_120000.jpg"
            good_photo = photos_dir / "photo_20260312_120001.jpg"
            bad_photo.write_bytes(b"x")
            good_photo.write_bytes(b"y")

            def fake_detect_person_count(photo_path, model=None, conf=None):
                if photo_path == str(bad_photo):
                    raise ValueError("need at least one array to stack")
                return 1

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_count",
                side_effect=fake_detect_person_count,
            ), patch.object(detect, "emit_status") as mock_status:
                cleanup_plan = detect.detect(str(photos_dir), str(screenshots_dir), dry_run=True)

        self.assertEqual(cleanup_plan, [])
        self.assertTrue(
            any(
                call.args and str(call.args[0]).startswith(f"WARNING Image Read Error {bad_photo}")
                for call in mock_status.call_args_list
            )
        )
        self.assertTrue(
            any(
                call.args and "Processed photos: 2/2" in str(call.args[0])
                for call in mock_status.call_args_list
            )
        )

    def test_detect_resumes_from_progress_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            result_csv = root / "results.csv"
            resume_file = root / "resume.json"
            photos_dir.mkdir()
            screenshots_dir.mkdir()

            photos = [
                photos_dir / "photo_20260312_120000.jpg",
                photos_dir / "photo_20260312_120001.jpg",
                photos_dir / "photo_20260312_120002.jpg",
            ]
            for photo in photos:
                photo.write_bytes(b"x")

            processed_paths = []

            def fake_detect_person_count(photo_path, model=None, conf=None):
                processed_paths.append(photo_path)
                return 1

            progress_calls = 0

            def interrupt_after_two_progress_messages(message):
                nonlocal progress_calls
                if str(message).startswith("Processed photos:"):
                    progress_calls += 1
                    if progress_calls == 2:
                        raise RuntimeError("stop after checkpoint")

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_count",
                side_effect=fake_detect_person_count,
            ), patch.object(detect, "emit_status", side_effect=interrupt_after_two_progress_messages):
                with self.assertRaisesRegex(RuntimeError, "stop after checkpoint"):
                    detect.detect(
                        str(photos_dir),
                        str(screenshots_dir),
                        dry_run=True,
                        result_csv_path=str(result_csv),
                        resume_file_path=str(resume_file),
                        batch_size=1,
                        progress_interval_seconds=0,
                    )

            with resume_file.open("r", encoding="utf-8") as fh:
                resume_state = json.load(fh)

            self.assertEqual(resume_state["processed_count"], 2)
            self.assertEqual(resume_state["last_photo_path"], str(photos[1]))

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_count",
                side_effect=fake_detect_person_count,
            ), patch.object(detect, "emit_status"):
                detect.detect(
                    str(photos_dir),
                    str(screenshots_dir),
                    dry_run=True,
                    result_csv_path=str(result_csv),
                    resume_file_path=str(resume_file),
                    batch_size=1,
                    progress_interval_seconds=0,
                )

            self.assertEqual(processed_paths, [str(photo) for photo in photos])

            with result_csv.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["photo_path"] for row in rows], [str(photo) for photo in photos])

    def test_detect_writes_csv_rows_in_real_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            result_csv = root / "results.csv"
            resume_file = root / "resume.json"
            photos_dir.mkdir()
            screenshots_dir.mkdir()

            no_person_photo = photos_dir / "photo_20260312_120000.jpg"
            with_person_photo = photos_dir / "photo_20260312_120001.jpg"
            no_person_photo.write_bytes(b"x")
            with_person_photo.write_bytes(b"y")

            def fake_detect_person_count(photo_path, model=None, conf=None):
                if photo_path == str(no_person_photo):
                    return 0
                return 2

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_count",
                side_effect=fake_detect_person_count,
            ), patch.object(
                detect,
                "get_screenshots_within_time_range",
                return_value=["C:/shots/screenshot_20260312_120000_monitor_1.jpg"],
            ), patch.object(detect, "emit_status"):
                cleanup_plan = detect.detect(
                    str(photos_dir),
                    str(screenshots_dir),
                    dry_run=True,
                    result_csv_path=str(result_csv),
                    resume_file_path=str(resume_file),
                    reset_progress=True,
                    batch_size=1,
                )

            with result_csv.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(len(cleanup_plan), 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "no_person")
        self.assertEqual(rows[0]["photo_path"], str(no_person_photo))
        self.assertEqual(rows[0]["screenshot_paths"], "C:/shots/screenshot_20260312_120000_monitor_1.jpg")
        self.assertEqual(rows[1]["status"], "with_people")
        self.assertEqual(rows[1]["person_count"], "2")
        self.assertTrue(rows[0]["processed_at"])
        self.assertTrue(rows[1]["processed_at"])

    def test_detect_batches_photo_inference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            result_csv = root / "results.csv"
            resume_file = root / "resume.json"
            photos_dir.mkdir()
            screenshots_dir.mkdir()

            photos = [
                photos_dir / "photo_20260312_120000.jpg",
                photos_dir / "photo_20260312_120001.jpg",
                photos_dir / "photo_20260312_120002.jpg",
            ]
            for photo in photos:
                photo.write_bytes(b"x")

            batch_calls = []

            def fake_detect_person_counts(photo_paths, model=None, conf=None):
                batch_calls.append(list(photo_paths))
                return [1] * len(photo_paths)

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_counts",
                side_effect=fake_detect_person_counts,
            ), patch.object(detect, "emit_status"):
                detect.detect(
                    str(photos_dir),
                    str(screenshots_dir),
                    dry_run=True,
                    result_csv_path=str(result_csv),
                    resume_file_path=str(resume_file),
                    reset_progress=True,
                    batch_size=2,
                )

        self.assertEqual(batch_calls, [[str(photos[0]), str(photos[1])], [str(photos[2])]])

    def test_detect_falls_back_to_single_in_failed_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            photos_dir = root / "photos"
            screenshots_dir = root / "screenshots"
            result_csv = root / "results.csv"
            resume_file = root / "resume.json"
            photos_dir.mkdir()
            screenshots_dir.mkdir()

            photos = [
                photos_dir / "photo_20260312_120000.jpg",
                photos_dir / "photo_20260312_120001.jpg",
                photos_dir / "photo_20260312_120002.jpg",
            ]
            for photo in photos:
                photo.write_bytes(b"x")

            batch_calls = []
            single_calls = []

            def fake_detect_person_counts(photo_paths, model=None, conf=None):
                batch_calls.append(list(photo_paths))
                if len(photo_paths) == 2:
                    raise ValueError("batch failed")
                return [1]

            def fake_detect_person_count(photo_path, model=None, conf=None):
                single_calls.append(photo_path)
                if photo_path == str(photos[1]):
                    return 0
                return 1

            with patch.object(detect, "get_yolo_model", return_value=object()), patch.object(
                detect,
                "detect_person_counts",
                side_effect=fake_detect_person_counts,
            ), patch.object(
                detect,
                "detect_person_count",
                side_effect=fake_detect_person_count,
            ), patch.object(
                detect,
                "get_screenshots_within_time_range",
                return_value=["C:/shots/screenshot_20260312_120001_monitor_1.jpg"],
            ), patch.object(detect, "emit_status"):
                cleanup_plan = detect.detect(
                    str(photos_dir),
                    str(screenshots_dir),
                    dry_run=True,
                    result_csv_path=str(result_csv),
                    resume_file_path=str(resume_file),
                    reset_progress=True,
                    batch_size=2,
                )

            with result_csv.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(batch_calls, [[str(photos[0]), str(photos[1])], [str(photos[2])]])
        self.assertEqual(single_calls, [str(photos[0]), str(photos[1])])
        self.assertEqual(len(cleanup_plan), 1)
        self.assertEqual(rows[1]["status"], "no_person")
        self.assertEqual(rows[1]["photo_path"], str(photos[1]))

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
