from pathlib import Path


def _assert_fragments_in_order(content, fragments):
    positions = [content.index(fragment) for fragment in fragments]
    assert positions == sorted(positions)


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


def test_run_dev_sh_detaches_backend_from_terminal_session():
    run_dev_sh = Path("RUN_DEV.sh").read_text(encoding="utf-8")

    assert "start_new_session=True" in run_dev_sh
    assert "nohup \"$PYTHON_BIN\" src/scripts/run_server_background.py" not in run_dev_sh


def test_run_bat_builds_and_silently_installs_latest_package():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert ".venv-backend-runtime-gpu" in run_bat
    assert "requirements-backend-runtime-gpu.txt" in run_bat
    assert "run_packaging_builds.py" in run_bat
    assert '"%BACKEND_RUNTIME_PYTHON%" src\\scripts\\verify_backend_runtime.py --timeout-seconds 60' in run_bat
    assert "call :RunElectronPackageWithFallback" in run_bat
    assert "npm run electron:package" in run_bat
    assert "npm run electron:build" not in run_bat
    assert "ArgumentList '/S'" in run_bat
    assert 'Filter \'Vantage Setup *.exe\'' in run_bat


def test_run_bat_retries_electron_downloads_with_mirror_fallback():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "VANTAGE_ELECTRON_MIRROR_FALLBACK" in run_bat
    assert "call :RunNpmInstallWithFallback" in run_bat
    assert "call :EnsureElectronBinary" in run_bat
    assert "call :RunElectronPackageWithFallback" in run_bat
    assert "Retrying Electron download with mirror fallback" in run_bat


def test_run_bat_primes_custom_nsis_archive_cache():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "CUSTOM_NSIS_BINARY_URL" in run_bat
    assert "CUSTOM_NSIS_BINARY_SHA256=374cfc092fd1bd1898472df627549ecc165b0d6ba88e82deba085673aec95336" in run_bat
    assert "call :EnsureCustomNsisArchiveCache" in run_bat
    assert "Custom NSIS archive cache ready" in run_bat


def test_run_bat_skips_reinstalling_backend_dependencies_when_requirements_hash_matches():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "BACKEND_RUNTIME_REQUIREMENTS_STAMP" in run_bat
    assert "VANTAGE_FORCE_BACKEND_DEPS" in run_bat
    assert "BACKEND_RUNTIME_DEPS_NEED_SYNC" in run_bat
    assert "Backend runtime dependencies already synced" in run_bat
    assert "backend runtime dependency imports ok" in run_bat
    assert "Backend runtime dependency import check failed" in run_bat


def test_backend_dependency_stamps_hash_shared_core_and_runtime_overlay():
    run_bat = Path("run.bat").read_text(encoding="utf-8")
    release_script = Path("scripts/build-release-installer.ps1").read_text(
        encoding="utf-8"
    )

    assert "BACKEND_RUNTIME_CORE_REQUIREMENTS" in run_bat
    assert "%PROJECT_ROOT%requirements-core.txt" in run_bat
    assert "BACKEND_RUNTIME_CORE_REQUIREMENTS_HASH" in run_bat
    assert (
        "!BACKEND_RUNTIME_CORE_REQUIREMENTS_HASH!:"
        "!BACKEND_RUNTIME_OVERLAY_REQUIREMENTS_HASH!"
    ) in run_bat

    assert "$BackendRuntimeCoreRequirements" in release_script
    assert 'Join-Path $ProjectRoot "requirements-core.txt"' in release_script
    assert "$coreRequirementsHash" in release_script
    assert '$requirementsHash = "${coreRequirementsHash}:$overlayRequirementsHash"' in release_script


def test_macos_launcher_dependency_stamps_hash_shared_core_and_runtime_overlay():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")

        assert (
            'BACKEND_RUNTIME_CORE_REQUIREMENTS="${PROJECT_ROOT}/requirements-core.txt"'
            in launcher
        )
        assert (
            'core_requirements_hash="$(shasum -a 256 '
            '"$BACKEND_RUNTIME_CORE_REQUIREMENTS" | awk \'{print $1}\')"'
            in launcher
        )
        assert (
            'overlay_requirements_hash="$(shasum -a 256 '
            '"$BACKEND_RUNTIME_REQUIREMENTS" | awk \'{print $1}\')"'
            in launcher
        )
        assert (
            'requirements_hash="${core_requirements_hash}:${overlay_requirements_hash}"'
            in launcher
        )

    run_dev = Path("RUN_DEV.sh").read_text(encoding="utf-8")
    assert '"$requirements_hash" == "$stored_codesign_hash"' in run_dev
    assert (
        "printf '%s\\n' \"$requirements_hash\" > \"$BACKEND_RUNTIME_CODESIGN_STAMP\""
        in run_dev
    )


def test_dependency_sync_normalizes_opencv_after_install_and_before_stamping():
    run_bat = Path("RUN.bat").read_text(encoding="utf-8")
    assert (
        'set "OPENCV_NORMALIZER=%PROJECT_ROOT%src\\scripts\\'
        'normalize_opencv_installation.py"'
    ) in run_bat
    run_bat_install = (
        '"%BACKEND_RUNTIME_PYTHON%" -m pip install -r '
        '"%BACKEND_RUNTIME_REQUIREMENTS%"'
    )
    run_bat_normalize = (
        '"%BACKEND_RUNTIME_PYTHON%" "%OPENCV_NORMALIZER%" '
        '--requirements-core "%BACKEND_RUNTIME_CORE_REQUIREMENTS%"'
    )
    run_bat_stamp = '> "%BACKEND_RUNTIME_REQUIREMENTS_STAMP%" echo'
    _assert_fragments_in_order(
        run_bat,
        (run_bat_install, run_bat_normalize, run_bat_stamp),
    )
    run_bat_normalize_block = run_bat[
        run_bat.index(run_bat_normalize) : run_bat.index(run_bat_stamp)
    ]
    assert "if errorlevel 1" in run_bat_normalize_block
    assert "exit /b 1" in run_bat_normalize_block

    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")
        assert (
            'OPENCV_NORMALIZER="${PROJECT_ROOT}/src/scripts/'
            'normalize_opencv_installation.py"'
        ) in launcher
        install = (
            '"$BACKEND_RUNTIME_PYTHON" -m pip install -r '
            '"$BACKEND_RUNTIME_REQUIREMENTS"'
        )
        normalize = (
            'if ! "$BACKEND_RUNTIME_PYTHON" "$OPENCV_NORMALIZER" '
            '--requirements-core "$BACKEND_RUNTIME_CORE_REQUIREMENTS"; then'
        )
        stamp = (
            "printf '%s\\n' \"$requirements_hash\" > "
            '"$BACKEND_RUNTIME_REQUIREMENTS_STAMP"'
        )
        _assert_fragments_in_order(launcher, (install, normalize, stamp))
        normalize_block = launcher[launcher.index(normalize) : launcher.index(stamp)]
        assert "exit 1" in normalize_block

    release_script = Path("scripts/build-release-installer.ps1").read_text(
        encoding="utf-8"
    )
    assert (
        '$OpenCvNormalizer = Join-Path $ProjectRoot '
        '"src\\scripts\\normalize_opencv_installation.py"'
    ) in release_script
    release_install = (
        "Invoke-Native -FilePath $BackendRuntimePython "
        '-ArgumentList @("-m", "pip", "install", "-r", '
        "$BackendRuntimeRequirements)"
    )
    release_normalize = (
        "Invoke-Native -FilePath $BackendRuntimePython "
        '-ArgumentList @($OpenCvNormalizer, "--requirements-core", '
        "$BackendRuntimeCoreRequirements)"
    )
    release_stamp = "Set-Content -LiteralPath $BackendRuntimeRequirementsStamp"
    _assert_fragments_in_order(
        release_script,
        (release_install, release_normalize, release_stamp),
    )


def test_run_bat_restores_source_build_info_after_packaging():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "WEBAPP_BUILD_INFO" in run_bat
    assert "RUN_BUILD_INFO_BACKUP" in run_bat
    assert "BUILD_INFO_BACKUP_CREATED" in run_bat
    assert "call :RestoreBuildInfo" in run_bat
    assert "Source build-info restored" in run_bat
    package_call = "call :RunElectronPackageWithFallback"
    assert run_bat.index("call node scripts\\prepare-build-version.mjs --mode auto") < run_bat.index(package_call)
    assert run_bat.index(package_call) < run_bat.rindex("call :RestoreBuildInfo")
    assert "npm run electron:package" in run_bat


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
