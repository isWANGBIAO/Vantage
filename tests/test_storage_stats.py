import asyncio
import tempfile
import unittest
import builtins
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import os as _stdlib_os
from src.backend import media as _backend_media
from src.backend import observability as _backend_observability
from src.backend import runtime as _backend_runtime
from src.backend import settings as _backend_settings
from src.backend import system as _backend_system


class StorageStatsTests(unittest.TestCase):
    def test_storage_budget_warning_is_limited_to_at_most_once_per_hour(self):
        self.assertGreaterEqual(_backend_media.STORAGE_SCAN_STATUS_LOG_INTERVAL_SECONDS, 3600.0)

    def test_sys_stats_preserves_cached_storage_total_and_partial_marker(self):
        original_state = (
            _backend_runtime.state.photos_size,
            _backend_runtime.state.screenshots_size,
            _backend_runtime.state.legacy_size,
            _backend_runtime.state.storage_scan_truncated,
        )
        try:
            _backend_runtime.state.photos_size = 1 * 1024**2
            _backend_runtime.state.screenshots_size = 2 * 1024**2
            _backend_runtime.state.legacy_size = 3 * 1024**2
            _backend_runtime.state.storage_scan_truncated = True
            with (
                patch.object(_backend_system.psutil, "cpu_percent", return_value=12.5),
                patch.object(
                    _backend_system.psutil,
                    "virtual_memory",
                    return_value=SimpleNamespace(
                        used=4 * 1024**3,
                        total=8 * 1024**3,
                        percent=50.0,
                    ),
                ),
                patch.object(
                    _backend_settings.shutil,
                    "disk_usage",
                    return_value=(10 * 1024**3, 4 * 1024**3, 6 * 1024**3),
                ),
            ):
                result = asyncio.run(_backend_system.get_sys_stats())
        finally:
            (
                _backend_runtime.state.photos_size,
                _backend_runtime.state.screenshots_size,
                _backend_runtime.state.legacy_size,
                _backend_runtime.state.storage_scan_truncated,
            ) = original_state

        self.assertEqual(result["storage_used_mb"], 6.0)
        self.assertTrue(result["storage_scan_truncated"])

    def test_safe_directory_size_skips_files_that_disappear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            good = tmp / "good.bin"
            missing = tmp / "missing.bin"
            good.write_bytes(b"abc")
            missing.write_bytes(b"12345")

            real_getsize = _stdlib_os.path.getsize

            def fake_getsize(path):
                if Path(path) == missing:
                    raise OSError("file disappeared")
                return real_getsize(path)

            with patch.object(_stdlib_os.path, "getsize", side_effect=fake_getsize):
                size = _backend_media._safe_directory_size(tmp)

        self.assertEqual(size, 3)

    def test_safe_directory_size_marks_truncated_when_entry_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.bin").write_bytes(b"a")
            (tmp / "b.bin").write_bytes(b"b")

            size = _backend_media._safe_directory_size(tmp, max_entries=1, max_seconds=None)

        self.assertEqual(size, 1)
        self.assertTrue(_backend_media._safe_directory_size.last_truncated)

    def test_safe_directory_size_budget_log_is_rate_limited_even_when_counts_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.bin").write_bytes(b"a")
            (tmp / "b.bin").write_bytes(b"b")
            (tmp / "c.bin").write_bytes(b"c")

            now = {"value": 100.0}
            messages = []
            _backend_observability._reset_status_logs("storage-size-budget")
            try:
                with (
                    patch.object(_backend_media.time, "monotonic", side_effect=lambda: now["value"]),
                    patch.object(builtins, "print", side_effect=lambda message: messages.append(message)),
                ):
                    _backend_media._safe_directory_size(tmp, max_entries=1, max_seconds=None)
                    _backend_media._safe_directory_size(tmp, max_entries=2, max_seconds=None)
            finally:
                _backend_observability._reset_status_logs("storage-size-budget")

        budget_messages = [
            message for message in messages if "Storage size scan budget reached" in message
        ]
        self.assertEqual(len(budget_messages), 1)

    def test_update_storage_stats_resumes_partial_scans_until_exact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            photos = tmp / "photos"
            screenshots = tmp / "screenshots"
            photos.mkdir()
            screenshots.mkdir()
            (photos / "a.bin").write_bytes(b"a")
            (photos / "b.bin").write_bytes(b"bc")
            (screenshots / "screen.bin").write_bytes(b"shot")
            snapshots = []
            original_state = (
                _backend_runtime.state.is_running,
                _backend_runtime.state.photos_path,
                _backend_runtime.state.screenshots_path,
                _backend_runtime.state.photos_size,
                _backend_runtime.state.screenshots_size,
                _backend_runtime.state.storage_scan_truncated,
            )

            def sleep_fn(seconds):
                snapshots.append(
                    (
                        _backend_runtime.state.photos_size,
                        _backend_runtime.state.screenshots_size,
                        _backend_runtime.state.storage_scan_truncated,
                        seconds,
                    )
                )
                if len(snapshots) == 3:
                    _backend_runtime.state.is_running = False

            try:
                _backend_runtime.state.is_running = True
                _backend_runtime.state.photos_path = str(photos)
                _backend_runtime.state.screenshots_path = str(screenshots)
                _backend_media.update_storage_stats(
                    max_entries_per_step=1,
                    max_seconds_per_step=None,
                    monotonic_clock=lambda: 0.0,
                    sleep_fn=sleep_fn,
                )
            finally:
                (
                    _backend_runtime.state.is_running,
                    _backend_runtime.state.photos_path,
                    _backend_runtime.state.screenshots_path,
                    _backend_runtime.state.photos_size,
                    _backend_runtime.state.screenshots_size,
                    _backend_runtime.state.storage_scan_truncated,
                ) = original_state

        # scandir ordering is filesystem-dependent; either file may be first.
        # Exact cumulative totals and the final completion marker remain fixed.
        self.assertEqual(len(snapshots), 3)
        self.assertIn(snapshots[0], [(1, 4, True, 60), (2, 4, True, 60)])
        self.assertEqual(snapshots[1:], [(3, 4, True, 60), (3, 4, False, 60)])

    def test_update_storage_stats_restarts_scanner_when_path_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first"
            second = tmp / "second"
            first.mkdir()
            second.mkdir()
            (first / "first.bin").write_bytes(b"a")
            (second / "second.bin").write_bytes(b"bc")
            observed_sizes = []
            original_state = (
                _backend_runtime.state.is_running,
                _backend_runtime.state.photos_path,
                _backend_runtime.state.screenshots_path,
                _backend_runtime.state.photos_size,
                _backend_runtime.state.screenshots_size,
                _backend_runtime.state.storage_scan_truncated,
            )

            def sleep_fn(_seconds):
                observed_sizes.append(_backend_runtime.state.photos_size)
                if len(observed_sizes) == 1:
                    _backend_runtime.state.photos_path = str(second)
                else:
                    _backend_runtime.state.is_running = False

            try:
                _backend_runtime.state.is_running = True
                _backend_runtime.state.photos_path = str(first)
                _backend_runtime.state.screenshots_path = None
                _backend_media.update_storage_stats(
                    max_entries_per_step=10,
                    max_seconds_per_step=None,
                    monotonic_clock=lambda: 0.0,
                    sleep_fn=sleep_fn,
                )
            finally:
                (
                    _backend_runtime.state.is_running,
                    _backend_runtime.state.photos_path,
                    _backend_runtime.state.screenshots_path,
                    _backend_runtime.state.photos_size,
                    _backend_runtime.state.screenshots_size,
                    _backend_runtime.state.storage_scan_truncated,
                ) = original_state

        self.assertEqual(observed_sizes, [1, 2])

    def test_update_storage_stats_closes_scanners_on_path_change_and_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first"
            second = tmp / "second"
            first.mkdir()
            second.mkdir()
            created = []
            original_state = (
                _backend_runtime.state.is_running,
                _backend_runtime.state.photos_path,
                _backend_runtime.state.screenshots_path,
                _backend_runtime.state.photos_size,
                _backend_runtime.state.screenshots_size,
                _backend_runtime.state.storage_scan_truncated,
            )

            class TrackingScanner:
                def __init__(self, root, **_kwargs):
                    self.root = Path(root)
                    self.closed = False
                    created.append(self)

                def step(self):
                    return SimpleNamespace(total_size=1, complete=False)

                def close(self):
                    self.closed = True

            cycles = []

            def sleep_fn(_seconds):
                cycles.append(len(cycles))
                if len(cycles) == 1:
                    _backend_runtime.state.photos_path = str(second)
                else:
                    _backend_runtime.state.is_running = False

            try:
                _backend_runtime.state.is_running = True
                _backend_runtime.state.photos_path = str(first)
                _backend_runtime.state.screenshots_path = None
                _backend_media.update_storage_stats(
                    max_entries_per_step=1,
                    max_seconds_per_step=None,
                    monotonic_clock=lambda: 0.0,
                    sleep_fn=sleep_fn,
                    scanner_factory=TrackingScanner,
                )
            finally:
                (
                    _backend_runtime.state.is_running,
                    _backend_runtime.state.photos_path,
                    _backend_runtime.state.screenshots_path,
                    _backend_runtime.state.photos_size,
                    _backend_runtime.state.screenshots_size,
                    _backend_runtime.state.storage_scan_truncated,
                ) = original_state

        self.assertEqual([scanner.root for scanner in created], [first, second])
        self.assertTrue(created[0].closed)
        self.assertTrue(created[1].closed)

    def test_update_storage_stats_does_not_probe_completed_path_before_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos = Path(tmpdir) / "photos"
            photos.mkdir()
            (photos / "photo.bin").write_bytes(b"photo")
            exists_counts = []
            exists_calls = []
            real_exists = _stdlib_os.path.exists
            original_state = (
                _backend_runtime.state.is_running,
                _backend_runtime.state.photos_path,
                _backend_runtime.state.screenshots_path,
                _backend_runtime.state.photos_size,
                _backend_runtime.state.screenshots_size,
                _backend_runtime.state.storage_scan_truncated,
            )

            def tracked_exists(path):
                exists_calls.append(path)
                return real_exists(path)

            def sleep_fn(_seconds):
                exists_counts.append(len(exists_calls))
                if len(exists_counts) == 2:
                    _backend_runtime.state.is_running = False

            try:
                _backend_runtime.state.is_running = True
                _backend_runtime.state.photos_path = str(photos)
                _backend_runtime.state.screenshots_path = None
                with patch.object(_stdlib_os.path, "exists", side_effect=tracked_exists):
                    _backend_media.update_storage_stats(
                        max_entries_per_step=10,
                        max_seconds_per_step=None,
                        monotonic_clock=lambda: 0.0,
                        sleep_fn=sleep_fn,
                    )
            finally:
                (
                    _backend_runtime.state.is_running,
                    _backend_runtime.state.photos_path,
                    _backend_runtime.state.screenshots_path,
                    _backend_runtime.state.photos_size,
                    _backend_runtime.state.screenshots_size,
                    _backend_runtime.state.storage_scan_truncated,
                ) = original_state

        self.assertEqual(exists_counts[1], exists_counts[0])

    def test_find_latest_file_recursive_marks_truncated_when_entry_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "a.jpg"
            second = tmp / "b.jpg"
            first.write_bytes(b"a")
            second.write_bytes(b"b")

            latest = _backend_media.find_latest_file_recursive(tmp, max_entries=1, max_seconds=None)

        self.assertIsNotNone(latest)
        self.assertTrue(_backend_media.find_latest_file_recursive.last_truncated)

    def test_find_latest_file_prefers_new_root_file_before_deep_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            nested = tmp / "nested"
            nested.mkdir()
            old = nested / "old.jpg"
            newest = tmp / "newest.jpg"
            old.write_bytes(b"old")
            newest.write_bytes(b"new")

            _stdlib_os.utime(old, (1000, 1000))
            _stdlib_os.utime(nested, (1000, 1000))
            _stdlib_os.utime(newest, (2000, 2000))

            latest = _backend_media.find_latest_file_recursive(tmp, max_entries=1, max_seconds=None)

        self.assertEqual(Path(latest).name, "newest.jpg")
        self.assertFalse(_backend_media.find_latest_file_recursive.last_truncated)


if __name__ == "__main__":
    unittest.main()
