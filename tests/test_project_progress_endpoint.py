import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import os as _stdlib_os
from src.backend import projects as _backend_projects
from src.backend import source_paths as _backend_source_paths


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )


def _make_activity_repo(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Vantage Test")
    _git(root, "config", "user.email", "vantage-test@example.invalid")
    project = root / "my project"
    unrelated = root / "other"
    project.mkdir()
    unrelated.mkdir()
    (project / "Prompt_Project_Management.md").write_text(
        "## 项目任务\n- [ ] 子项目任务\n", encoding="utf-8"
    )
    _git(root, "add", "--", "my project/Prompt_Project_Management.md")
    _git(root, "commit", "-qm", "project-only activity")
    (unrelated / "other.txt").write_text("outside project", encoding="utf-8")
    _git(root, "add", "--", "other/other.txt")
    _git(root, "commit", "-qm", "unrelated activity")
    return project


class ProjectProgressEndpointTests(unittest.TestCase):
    def test_nested_project_activity_excludes_sibling_commits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = Path(tmpdir)
            project = _make_activity_repo(repository)
            with patch.dict(os.environ, {"AI_DATA_ROOT": str(project)}):
                payload = asyncio.run(_backend_projects.get_project_progress())

        self.assertEqual([item["message"] for item in payload["commits"]], ["project-only activity"])

    def test_repository_root_project_activity_keeps_all_repo_commits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = Path(tmpdir)
            _make_activity_repo(repository)
            (repository / "Prompt_Project_Management.md").write_text(
                "## 项目任务\n- [ ] 根目录任务\n", encoding="utf-8"
            )
            _git(repository, "add", "--", "Prompt_Project_Management.md")
            _git(repository, "commit", "-qm", "root project activity")
            with patch.dict(os.environ, {"AI_DATA_ROOT": str(repository)}):
                payload = asyncio.run(_backend_projects.get_project_progress())

        self.assertEqual(
            [item["message"] for item in payload["commits"]],
            ["root project activity", "unrelated activity", "project-only activity"],
        )

    def test_personal_project_prompt_does_not_use_bundled_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            personal = root / "personal"
            bundled = root / "bundled"
            personal.mkdir()
            bundled.mkdir()
            (personal / "Prompt_Project_Management.md").write_text(
                "## 我的项目任务\n- [x] 已完成个人任务\n", encoding="utf-8"
            )
            (bundled / "Prompt_Project_Management.md").write_text(
                "## 打包项目任务\n- [ ] 旧任务\n", encoding="utf-8"
            )
            (bundled / "project_activity.json").write_text(
                json.dumps({"commits": [{"hash": "old", "date": "2026-01-01", "message": "bundled"}]}),
                encoding="utf-8",
            )
            (personal / "project_activity.json").write_text(
                json.dumps({"commits": [{"hash": "wrong", "date": "2026-01-02", "message": "personal snapshot"}]}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"AI_DATA_ROOT": str(personal)}), patch.object(
                _backend_projects, "_packaged_resource_root", return_value=bundled
            ):
                payload = asyncio.run(_backend_projects.get_project_progress())

        self.assertEqual(payload["tasks"]["completed"][0]["task"], "已完成个人任务")
        self.assertEqual(payload["commits"], [])

    def test_personal_project_prompt_is_reread_on_each_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            personal = Path(tmpdir)
            source = personal / "Prompt_Project_Management.md"
            source.write_text("## 项目任务\n- [ ] 初始任务\n", encoding="utf-8")
            with patch.dict(os.environ, {"AI_DATA_ROOT": str(personal)}):
                first = asyncio.run(_backend_projects.get_project_progress())
                source.write_text("## 项目任务\n- [x] 最新任务\n- [ ] 另一个任务\n", encoding="utf-8")
                second = asyncio.run(_backend_projects.get_project_progress())

        self.assertEqual(first["tasks"]["pending"][0]["task"], "初始任务")
        self.assertEqual(second["tasks"]["completed"][0]["task"], "最新任务")
        self.assertEqual(second["stats"]["total_tasks"], 2)

    def test_personal_project_without_git_never_uses_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            personal = Path(tmpdir)
            (personal / "Prompt_Project_Management.md").write_text(
                "## 项目任务\n- [ ] 待办\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {"AI_DATA_ROOT": str(personal)}), patch.object(
                _backend_projects.subprocess, "run"
            ) as git_run:
                payload = asyncio.run(_backend_projects.get_project_progress())
        self.assertEqual(payload["commits"], [])
        git_run.assert_not_called()

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
            original_abspath = _stdlib_os.path.abspath

            def fake_abspath(path):
                if path == _backend_source_paths.SERVER_FILE:
                    return os.path.join(src_dir, "server.py")
                return original_abspath(path)

            with patch.object(_stdlib_os.path, "abspath", side_effect=fake_abspath), patch.object(
                _backend_projects.DataLoader,
                "resolve_data_path",
                return_value=resource_root / "Prompt_Project_Management.md",
            ), patch.object(
                _backend_projects.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=128, stdout=b"", stderr=b"not a git repo"),
            ):
                payload = asyncio.run(_backend_projects.get_project_progress())

        self.assertEqual(payload["commits"], [{"hash": "abc1234", "date": "2026-04-24", "message": "fix packaged progress"}])
        self.assertEqual(payload["stats"]["total_tasks"], 2)


if __name__ == "__main__":
    unittest.main()
