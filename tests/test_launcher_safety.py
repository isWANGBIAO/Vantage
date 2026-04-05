from pathlib import Path


def test_run_bat_does_not_use_global_process_kills():
    content = Path("run.bat").read_text(encoding="utf-8")

    assert 'taskkill /F /IM electron.exe' not in content
    assert 'find ":5173"' not in content
    assert 'find ":8000"' not in content
    assert 'cleanup_vantage_python_processes.py' in content


def test_backend_launchers_do_not_wrap_server_in_cmd_windows():
    run_bat = Path("run.bat").read_text(encoding="utf-8")
    start_webapp = Path("START_WEBAPP.bat").read_text(encoding="utf-8")

    assert 'cmd /c "cd /d %PROJECT_ROOT% && python src/server.py' not in run_bat
    assert 'run_server_background.py' in run_bat

    assert 'cmd /k "python src/server.py"' not in start_webapp
    assert 'run_server_background.py' in start_webapp


def test_run_bat_launches_frontend_via_background_runner():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "call npm run electron:start" not in run_bat
    assert "call npm run electron:dev" not in run_bat
    assert "run_frontend_background.py production" in run_bat
    assert "run_frontend_background.py development" in run_bat
