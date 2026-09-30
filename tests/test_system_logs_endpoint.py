import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import observability as _backend_observability


class _FakeDateTime:
    @classmethod
    def now(cls):
        return _backend_observability.datetime(2026, 4, 20, 22, 15, 30)


class SystemLogsEndpointTests(unittest.TestCase):
    def test_get_system_logs_reads_latest_runtime_log_pointer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            logs_dir = tmp / "logs"
            runtime_dir = logs_dir / "server"
            runtime_dir.mkdir(parents=True)
            runtime_log = runtime_dir / "server-20260420_221530.log"
            runtime_log.write_text("line1\nline2\n", encoding="utf-8")
            (logs_dir / "server.latest.log").write_text(str(runtime_log.resolve()), encoding="utf-8")

            with patch.object(_backend_observability.Config, "get_logs_dir", return_value=logs_dir):
                payload = asyncio.run(_backend_observability.get_system_logs())

        self.assertEqual(payload["logs"], ["line1\n", "line2\n"])
