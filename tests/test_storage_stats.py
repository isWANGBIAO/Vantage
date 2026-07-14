import tempfile
import unittest
import builtins
from pathlib import Path
from unittest.mock import patch

from src import server


class StorageStatsTests(unittest.TestCase):
    def test_storage_budget_warning_is_limited_to_at_most_once_per_hour(self):
        self.assertGreaterEqual(server.STORAGE_SCAN_STATUS_LOG_INTERVAL_SECONDS, 3600.0)

    def test_safe_directory_size_skips_files_that_disappear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            good = tmp / "good.bin"
            missing = tmp / "missing.bin"
            good.write_bytes(b"abc")
            missing.write_bytes(b"12345")

            real_getsize = server.os.path.getsize

            def fake_getsize(path):
                if Path(path) == missing:
                    raise OSError("file disappeared")
                return real_getsize(path)

            with patch.object(server.os.path, "getsize", side_effect=fake_getsize):
                size = server._safe_directory_size(tmp)

        self.assertEqual(size, 3)

    def test_safe_directory_size_marks_truncated_when_entry_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.bin").write_bytes(b"a")
            (tmp / "b.bin").write_bytes(b"b")

            size = server._safe_directory_size(tmp, max_entries=1, max_seconds=None)

        self.assertEqual(size, 1)
        self.assertTrue(server._safe_directory_size.last_truncated)

    def test_safe_directory_size_budget_log_is_rate_limited_even_when_counts_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.bin").write_bytes(b"a")
            (tmp / "b.bin").write_bytes(b"b")
            (tmp / "c.bin").write_bytes(b"c")

            now = {"value": 100.0}
            messages = []
            server._reset_status_logs("storage-size-budget")
            try:
                with (
                    patch.object(server.time, "monotonic", side_effect=lambda: now["value"]),
                    patch.object(builtins, "print", side_effect=lambda message: messages.append(message)),
                ):
                    server._safe_directory_size(tmp, max_entries=1, max_seconds=None)
                    server._safe_directory_size(tmp, max_entries=2, max_seconds=None)
            finally:
                server._reset_status_logs("storage-size-budget")

        budget_messages = [
            message for message in messages if "Storage size scan budget reached" in message
        ]
        self.assertEqual(len(budget_messages), 1)

    def test_find_latest_file_recursive_marks_truncated_when_entry_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "a.jpg"
            second = tmp / "b.jpg"
            first.write_bytes(b"a")
            second.write_bytes(b"b")

            latest = server.find_latest_file_recursive(tmp, max_entries=1, max_seconds=None)

        self.assertIsNotNone(latest)
        self.assertTrue(server.find_latest_file_recursive.last_truncated)

    def test_find_latest_file_prefers_new_root_file_before_deep_budget_is_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            nested = tmp / "nested"
            nested.mkdir()
            old = nested / "old.jpg"
            newest = tmp / "newest.jpg"
            old.write_bytes(b"old")
            newest.write_bytes(b"new")

            server.os.utime(old, (1000, 1000))
            server.os.utime(nested, (1000, 1000))
            server.os.utime(newest, (2000, 2000))

            latest = server.find_latest_file_recursive(tmp, max_entries=1, max_seconds=None)

        self.assertEqual(Path(latest).name, "newest.jpg")
        self.assertFalse(server.find_latest_file_recursive.last_truncated)


if __name__ == "__main__":
    unittest.main()
