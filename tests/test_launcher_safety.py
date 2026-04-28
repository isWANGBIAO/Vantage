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

    assert ".venv-backend-runtime-gpu" in run_bat
    assert "requirements-backend-runtime-gpu.txt" in run_bat
    assert "run_packaging_builds.py" in run_bat
    assert '"%BACKEND_RUNTIME_PYTHON%" src\\scripts\\verify_backend_runtime.py --timeout-seconds 60' in run_bat
    assert "npm run electron:package" in run_bat
    assert "npm run electron:build" not in run_bat
    assert "ArgumentList '/S'" in run_bat
    assert 'Filter \'Vantage Setup *.exe\'' in run_bat


def test_run_bat_skips_reinstalling_backend_dependencies_when_requirements_hash_matches():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "BACKEND_RUNTIME_REQUIREMENTS_STAMP" in run_bat
    assert "VANTAGE_FORCE_BACKEND_DEPS" in run_bat
    assert "Backend runtime dependencies already synced" in run_bat


def test_run_bat_prints_step_timings():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert ":StepStart" in run_bat
    assert ":StepDone" in run_bat
    assert "Total elapsed" in run_bat


def test_packaging_build_orchestrator_runs_frontend_and_backend_builds_in_parallel():
    source = Path("src/scripts/run_packaging_builds.py").read_text(encoding="utf-8")

    assert "ThreadPoolExecutor" in source
    assert "reconfigure(encoding=\"utf-8\", errors=\"replace\")" in source
    assert "build_backend_runtime.py" in source
    assert "--reuse-if-unchanged" in source
    assert "npm" in source
    assert "run" in source
    assert "build" in source


def test_run_bat_exposes_parallel_build_worker_control():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "VANTAGE_BUILD_WORKERS" in run_bat
    assert "--workers" in run_bat
    assert "Build workers requested" in run_bat
    assert "VANTAGE_INSTALLER_COMPRESSION" not in run_bat
    assert "--config.compression" not in run_bat
