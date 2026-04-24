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


if __name__ == "__main__":
    unittest.main()
