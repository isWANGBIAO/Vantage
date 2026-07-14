import importlib.util
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def _load_launcher_module():
    module_path = Path("src/scripts/run_server_background.py")
    spec = importlib.util.spec_from_file_location("run_server_background", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_prepare_server_runtime_log_creates_timestamped_log_and_latest_pointer(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    launched_at = datetime(2026, 4, 20, 22, 15, 30)

    log_path, latest_pointer = launcher._prepare_server_runtime_log(logs_dir, launched_at)

    assert log_path == logs_dir / "server" / "server-20260420_221530.log"
    assert log_path.parent.exists()
    assert latest_pointer == logs_dir / "server.latest.log"
    assert latest_pointer.read_text(encoding="utf-8") == str(log_path.resolve())


def test_prepare_server_runtime_log_does_not_require_fixed_server_log(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    launched_at = datetime(2026, 4, 20, 22, 16, 0)
    legacy_log = logs_dir / "server.log"
    logs_dir.mkdir()
    legacy_log.write_text("legacy session still locked elsewhere\n", encoding="utf-8")

    log_path, latest_pointer = launcher._prepare_server_runtime_log(logs_dir, launched_at)

    assert legacy_log.exists()
    assert log_path == logs_dir / "server" / "server-20260420_221600.log"
    assert latest_pointer.read_text(encoding="utf-8") == str(log_path.resolve())


def test_resolve_runtime_context_uses_config_runtime_contract(tmp_path):
    launcher = _load_launcher_module()
    project_root = tmp_path / "repo"
    runtime_paths = {
        "log_dir": tmp_path / "appdata" / "logs",
    }
    runtime_env = {
        "VANTAGE_APP_MODE": "development",
        "VANTAGE_LOG_DIR": str(runtime_paths["log_dir"]),
    }

    with patch.object(launcher.Config, "get_project_root", return_value=project_root), patch.object(
        launcher.Config,
        "get_runtime_paths",
        return_value=runtime_paths,
    ), patch.object(
        launcher.Config,
        "build_runtime_environment",
        return_value=runtime_env,
    ):
        context = launcher._resolve_runtime_context()

    assert context["project_root"] == project_root
    assert context["log_dir"] == runtime_paths["log_dir"]
    assert context["env"] == runtime_env


def test_ensure_project_root_on_sys_path_returns_repo_root():
    launcher = _load_launcher_module()

    repo_root = launcher._ensure_project_root_on_sys_path(
        script_path=Path("src/scripts/run_server_background.py").resolve(),
        path_list=[],
    )

    assert repo_root == Path("src/scripts/run_server_background.py").resolve().parents[2]


def test_run_server_entrypoint_uses_run_path_in_development_mode(tmp_path):
    launcher = _load_launcher_module()
    project_root = tmp_path / "repo"
    run_calls = []

    mode = launcher._run_server_entrypoint(
        project_root,
        is_frozen=False,
        run_path=lambda path, run_name: run_calls.append((path, run_name)),
    )

    assert mode == "script"
    assert run_calls == [(str(project_root / "src" / "server.py"), "__main__")]


def test_run_server_entrypoint_calls_server_main_in_frozen_mode(tmp_path):
    launcher = _load_launcher_module()
    project_root = tmp_path / "runtime"
    called = []

    mode = launcher._run_server_entrypoint(
        project_root,
        is_frozen=True,
        server_main=lambda: called.append("server-main"),
    )

    assert mode == "frozen"
    assert called == ["server-main"]


def test_run_server_entrypoint_validates_required_imports_in_frozen_mode(tmp_path):
    launcher = _load_launcher_module()
    project_root = tmp_path / "runtime"
    calls = []

    launcher._run_server_entrypoint(
        project_root,
        is_frozen=True,
        server_main=lambda: calls.append("server-main"),
        validate_runtime_imports=lambda: calls.append("validate-imports"),
    )

    assert calls == ["validate-imports", "server-main"]


def test_validate_packaged_runtime_imports_reports_missing_modules():
    launcher = _load_launcher_module()

    def fake_import(module_name):
        if module_name == "zhdate":
            raise ModuleNotFoundError("No module named 'zhdate'")
        return object()

    try:
        launcher._validate_packaged_runtime_imports(import_module=fake_import)
    except RuntimeError as exc:
        assert "Missing packaged runtime module(s): zhdate" in str(exc)
        assert "No module named 'zhdate'" in str(exc)
    else:
        raise AssertionError("missing packaged runtime module did not fail validation")


def test_run_prompt_entrypoint_delegates_args_to_run_prompt_main():
    launcher = _load_launcher_module()
    captured_argv = []

    def fake_main():
        captured_argv.extend(launcher.sys.argv)

    launcher._run_prompt_entrypoint(
        ["--model", "gpt-5.3-codex-spark"],
        run_prompt_main=fake_main,
    )

    assert captured_argv == ["run_prompt.py", "--model", "gpt-5.3-codex-spark"]


def test_configure_frozen_runtime_search_paths_adds_internal_runtime_dirs(tmp_path):
    launcher = _load_launcher_module()
    resource_root = tmp_path / "runtime" / "_internal"
    runtime_root = resource_root.parent
    cv2_lib = resource_root / "cv2"
    numpy_libs = resource_root / "numpy.libs"
    cv2_lib.mkdir(parents=True)
    numpy_libs.mkdir(parents=True)

    added_paths = []
    env = {"PATH": r"C:\Windows\System32"}

    launcher._configure_frozen_runtime_search_paths(
        resource_root=resource_root,
        env=env,
        add_dll_directory=lambda value: added_paths.append(value),
    )

    assert env["PATH"].split(os.pathsep)[:4] == [
        str(resource_root),
        str(runtime_root),
        str(cv2_lib),
        str(numpy_libs),
    ]
    assert added_paths == [
        str(resource_root),
        str(runtime_root),
        str(cv2_lib),
        str(numpy_libs),
    ]


def test_launcher_does_not_preload_obsolete_torch_libraries():
    launcher = _load_launcher_module()
    source = Path(launcher.__file__).read_text(encoding="utf-8")

    assert "preload_torch" not in source
    assert "_preload_frozen_torch_libraries" not in source
