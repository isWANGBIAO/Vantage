from pathlib import Path


def test_run_bat_release_flow_keeps_source_cleanup_scoped():
    content = Path("run.bat").read_text(encoding="utf-8")

    assert 'taskkill /F /IM electron.exe' not in content
    assert 'find ":5173"' not in content
    assert 'find ":8000"' not in content
    assert 'cleanup_vantage_python_processes.py' in content
    assert 'taskkill /IM Vantage.exe /F' in content
    assert 'taskkill /IM VantageBackend.exe /F' in content


def test_development_launchers_do_not_wrap_server_in_cmd_windows():
    run_dev_bat = Path("RUN_DEV.bat").read_text(encoding="utf-8")
    start_webapp = Path("START_WEBAPP.bat").read_text(encoding="utf-8")

    assert 'cmd /c "cd /d %PROJECT_ROOT% && python src/server.py' not in run_dev_bat
    assert 'run_server_background.py' in run_dev_bat

    assert 'cmd /k "python src/server.py"' not in start_webapp
    assert 'run_server_background.py' in start_webapp


def test_run_dev_bat_launches_frontend_via_background_runner():
    run_dev_bat = Path("RUN_DEV.bat").read_text(encoding="utf-8")

    assert "call npm run electron:start" not in run_dev_bat
    assert "call npm run electron:dev" not in run_dev_bat
    assert "run_frontend_background.py production" in run_dev_bat
    assert "run_frontend_background.py development" in run_dev_bat


def test_run_dev_bat_does_not_block_launch_on_camera_readiness():
    run_dev_bat = Path("RUN_DEV.bat").read_text(encoding="utf-8")

    assert "Backend ready (camera offline)" in run_dev_bat
    assert "Waiting for backend/camera..." not in run_dev_bat
    assert "Backend did not become camera-ready" not in run_dev_bat


def test_run_bat_builds_and_silently_installs_latest_package():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "build_backend_runtime.py" in run_bat
    assert "verify_backend_runtime.py --timeout-seconds 60" in run_bat
    assert "npm run electron:build" in run_bat
    assert "ArgumentList '/S'" in run_bat
    assert 'Filter \'Vantage Setup *.exe\'' in run_bat
