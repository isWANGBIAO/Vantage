import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server


class StorageStatsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
