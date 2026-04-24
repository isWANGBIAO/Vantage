import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import server


class ProjectProgressEndpointTests(unittest.TestCase):
    def test_project_progress_uses_packaged_activity_snapshot_when_git_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            resource_root = Path(tmpdir) / "_internal"
            src_dir = resource_root / "src"
            src_dir.mkdir(parents=True)
            (resource_root / "Prompt_Project_Management.md").write_text(
                "## 项目任务\n- [x] 已完成\n- [ ] 待处理\n",
                encoding="utf-8",
            )
            (resource_root / "project_activity.json").write_text(
                json.dumps(
                    {
                        "commits": [
                            {
                                "hash": "abc1234",
                                "date": "2026-04-24",
                                "message": "fix packaged progress",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            original_abspath = server.os.path.abspath

            def fake_abspath(path):
                if path == server.__file__:
                    return os.path.join(src_dir, "server.py")
                return original_abspath(path)

            with patch.object(server.os.path, "abspath", side_effect=fake_abspath), patch.object(
                server.Config,
                "get_project_root",
                return_value=resource_root,
            ), patch.object(
                server.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=128, stdout=b"", stderr=b"not a git repo"),
            ):
                payload = asyncio.run(server.get_project_progress())

        self.assertEqual(payload["commits"], [{"hash": "abc1234", "date": "2026-04-24", "message": "fix packaged progress"}])
        self.assertEqual(payload["stats"]["total_tasks"], 2)


if __name__ == "__main__":
    unittest.main()
