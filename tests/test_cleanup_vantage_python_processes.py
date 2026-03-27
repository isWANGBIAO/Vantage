import os
import unittest
from pathlib import Path

from src.scripts import cleanup_vantage_python_processes as cleanup_script


class _FakeProcess:
    def __init__(self, pid, name, cmdline, cwd):
        self.pid = pid
        self._name = name
        self._cmdline = cmdline
        self._cwd = cwd

    def name(self):
        return self._name

    def cmdline(self):
        return self._cmdline

    def cwd(self):
        return self._cwd


class CleanupVantagePythonProcessesTests(unittest.TestCase):
    def setUp(self):
        self.project_root = Path("C:/Users/97012/gitee/ai")

    def test_matches_python_server_script_in_project(self):
        process = _FakeProcess(
            pid=1234,
            name="python.exe",
            cmdline=["python", "src/server.py"],
            cwd=str(self.project_root),
        )

        self.assertTrue(cleanup_script.is_vantage_server_process(process, self.project_root))

    def test_matches_inline_uvicorn_from_project_root(self):
        process = _FakeProcess(
            pid=1234,
            name="python.exe",
            cmdline=[
                "python",
                "-c",
                "import uvicorn; from src.server import app; uvicorn.run(app, host='127.0.0.1', port=8010)",
            ],
            cwd=str(self.project_root),
        )

        self.assertTrue(cleanup_script.is_vantage_server_process(process, self.project_root))

    def test_skips_unrelated_python_processes(self):
        process = _FakeProcess(
            pid=5678,
            name="python.exe",
            cmdline=["python", "c:/Users/97012/.vscode/extensions/ms-python.black-formatter/lsp_server.py"],
            cwd=str(self.project_root),
        )

        self.assertFalse(cleanup_script.is_vantage_server_process(process, self.project_root))

    def test_skips_current_python_process(self):
        process = _FakeProcess(
            pid=os.getpid(),
            name="python.exe",
            cmdline=["python", "src/server.py"],
            cwd=str(self.project_root),
        )

        self.assertFalse(cleanup_script.is_vantage_server_process(process, self.project_root))

    def test_matches_project_electron_process(self):
        process = _FakeProcess(
            pid=2468,
            name="electron.exe",
            cmdline=[
                "electron.exe",
                str(self.project_root / "src" / "webapp" / "main.cjs"),
            ],
            cwd=str(self.project_root / "src" / "webapp"),
        )

        self.assertTrue(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_matches_electron_child_process_with_app_path(self):
        process = _FakeProcess(
            pid=2469,
            name="electron.exe",
            cmdline=[
                "electron.exe",
                f"--app-path={self.project_root / 'src' / 'webapp'}",
            ],
            cwd="D:/temp",
        )

        self.assertTrue(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_matches_node_wrapper_for_electron_cli(self):
        process = _FakeProcess(
            pid=2470,
            name="node.exe",
            cmdline=[
                "node.exe",
                str(self.project_root / "src" / "webapp" / "node_modules" / "electron" / "cli.js"),
                ".",
            ],
            cwd="D:/temp",
        )

        self.assertTrue(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_matches_npm_wrapper_for_electron_dev_script(self):
        process = _FakeProcess(
            pid=2471,
            name="npm.exe",
            cmdline=["npm.exe", "run", "electron:dev"],
            cwd=str(self.project_root / "src" / "webapp"),
        )

        self.assertTrue(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_skips_other_project_npm_wrapper_for_electron_dev_script(self):
        process = _FakeProcess(
            pid=2472,
            name="npm.exe",
            cmdline=["npm.exe", "run", "electron:dev"],
            cwd="D:/other-project/src/webapp",
        )

        self.assertFalse(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_skips_other_project_electron_child_process_with_app_path(self):
        process = _FakeProcess(
            pid=2473,
            name="electron.exe",
            cmdline=["electron.exe", "--app-path=D:/other-project/src/webapp"],
            cwd="D:/temp",
        )

        self.assertFalse(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_skips_unrelated_electron_process(self):
        process = _FakeProcess(
            pid=8642,
            name="electron.exe",
            cmdline=["electron.exe", "D:/other-app/main.cjs"],
            cwd="D:/other-app",
        )

        self.assertFalse(cleanup_script.is_vantage_desktop_process(process, self.project_root))

    def test_skips_repo_local_node_script_without_desktop_entrypoint(self):
        process = _FakeProcess(
            pid=9753,
            name="node.exe",
            cmdline=["node.exe", "scripts/custom-task.js"],
            cwd=str(self.project_root),
        )

        self.assertFalse(cleanup_script.is_vantage_desktop_process(process, self.project_root))


if __name__ == "__main__":
    unittest.main()
