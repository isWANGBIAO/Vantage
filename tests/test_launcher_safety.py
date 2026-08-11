from pathlib import Path


def _assert_fragments_in_order(content, fragments):
    missing = [fragment for fragment in fragments if fragment not in content]
    assert not missing, f"Missing ordered fragments: {missing}"
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
    assert "run_with_backend_runtime_lock.py" in run_bat
    assert '"%BACKEND_RUNTIME_PYTHON%" src\\scripts\\verify_backend_runtime.py --timeout-seconds 60' in run_bat
    assert "call :RunElectronPackageWithFallback" in run_bat
    assert "npm run electron:package" in run_bat
    assert "npm run electron:build" not in run_bat
    assert "ArgumentList '/S'" in run_bat
    assert 'Filter \'Vantage Setup *.exe\'' in run_bat


def test_run_bat_retries_electron_downloads_with_mirror_fallback():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "VANTAGE_ELECTRON_MIRROR_FALLBACK" in run_bat
    assert "scripts\\sync-dependencies.cjs" in run_bat
    assert "call :EnsureElectronBinary" in run_bat
    assert "call :RunElectronPackageWithFallback" in run_bat
    assert "Retrying Electron download with mirror fallback" in run_bat


def test_persistent_launchers_share_validated_frontend_dependency_sync():
    run_bat = Path("RUN.bat").read_text(encoding="utf-8")
    run_sh = Path("RUN.sh").read_text(encoding="utf-8")
    run_dev_sh = Path("RUN_DEV.sh").read_text(encoding="utf-8")
    release_script = Path("scripts/build-release-installer.ps1").read_text(
        encoding="utf-8"
    )

    sync_cli = "scripts\\sync-dependencies.cjs"
    assert f"src\\webapp\\{sync_cli}" in run_bat
    assert "scripts/sync-dependencies.cjs" in run_sh
    assert "scripts/sync-dependencies.cjs" in run_dev_sh
    assert sync_cli in release_script

    assert 'if not exist "%PROJECT_ROOT%src\\webapp\\node_modules"' not in run_bat
    assert 'npm --prefix "${FRONTEND_ROOT}" install' not in run_sh
    assert 'npm --prefix "${FRONTEND_ROOT}" install' not in run_dev_sh
    assert 'Join-Path $WebappRoot "node_modules"' not in release_script

    assert "call npm install" not in run_bat
    assert '@("install")' not in release_script

    assert run_bat.index(sync_cli) < run_bat.index("call :EnsureElectronBinary")
    assert release_script.index(sync_cli) < release_script.index(
        'Invoke-WithElectronMirrorFallback -Description "Electron binary preparation"'
    )


def test_macos_frontend_sync_invalidates_native_stamp_before_resigning():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")
        sync_call = 'node "${FRONTEND_ROOT}/scripts/sync-dependencies.cjs"'
        invalidate_argument = (
            '--invalidate-stamp "$FRONTEND_NATIVE_CODESIGN_STAMP"'
        )
        codesign_call = "codesign_macos_frontend_binaries"

        sync_index = launcher.index(sync_call)
        invalidate_index = launcher.index(invalidate_argument, sync_index)
        codesign_index = launcher.index(codesign_call, invalidate_index)
        assert sync_index < invalidate_index < codesign_index


def test_run_bat_primes_custom_nsis_archive_cache():
    run_bat = Path("run.bat").read_text(encoding="utf-8")

    assert "CUSTOM_NSIS_BINARY_URL" in run_bat
    assert "CUSTOM_NSIS_BINARY_SHA256=374cfc092fd1bd1898472df627549ecc165b0d6ba88e82deba085673aec95336" in run_bat
    assert "call :EnsureCustomNsisArchiveCache" in run_bat
    assert "Custom NSIS archive cache ready" in run_bat


def test_persistent_launchers_share_backend_environment_sync_cli():
    launchers = {
        Path("RUN.bat"): Path("RUN.bat").read_text(encoding="utf-8"),
        Path("RUN.sh"): Path("RUN.sh").read_text(encoding="utf-8"),
        Path("RUN_DEV.sh"): Path("RUN_DEV.sh").read_text(encoding="utf-8"),
        Path("scripts/build-release-installer.ps1"): Path(
            "scripts/build-release-installer.ps1"
        ).read_text(encoding="utf-8"),
    }

    for path, launcher in launchers.items():
        assert "sync_backend_runtime_environment.py" in launcher, path
        assert "requirements-core.txt" in launcher, path
        assert "requirements-backend-runtime-gpu.txt" in launcher, path
        assert "normalize_opencv_installation.py" in launcher, path
        assert "VANTAGE_FORCE_BACKEND_DEPS" in launcher, path
        assert ".requirements-backend-runtime-gpu.sha256" not in launcher, path
        assert "pip install -r" not in launcher, path
        assert '"pip", "install", "-r"' not in launcher, path

    assert "BACKEND_RUNTIME_DEPS_NEED_SYNC" not in launchers[Path("RUN.bat")]
    assert "BACKEND_RUNTIME_CORE_REQUIREMENTS_HASH" not in launchers[Path("RUN.bat")]
    assert "BACKEND_RUNTIME_OVERLAY_REQUIREMENTS_HASH" not in launchers[Path("RUN.bat")]
    assert "Set-Content -LiteralPath $BackendRuntimeRequirementsStamp" not in launchers[
        Path("scripts/build-release-installer.ps1")
    ]


def test_target_backend_runtime_consumers_use_the_shared_lock_supervisor():
    run_bat = Path("RUN.bat").read_text(encoding="utf-8")
    run_sh = Path("RUN.sh").read_text(encoding="utf-8")
    run_dev_sh = Path("RUN_DEV.sh").read_text(encoding="utf-8")
    release_script = Path("scripts/build-release-installer.ps1").read_text(
        encoding="utf-8"
    )

    supervisor = "run_with_backend_runtime_lock.py"
    for path, content in (
        (Path("RUN.bat"), run_bat),
        (Path("RUN.sh"), run_sh),
        (Path("RUN_DEV.sh"), run_dev_sh),
        (Path("scripts/build-release-installer.ps1"), release_script),
    ):
        assert supervisor in content, path

    for command in ("run_packaging_builds.py", "verify_backend_runtime.py"):
        bat_command = run_bat[run_bat.index(command) - 240 : run_bat.index(command) + 240]
        shell_command = run_sh[run_sh.index(command) - 240 : run_sh.index(command) + 240]
        release_command = release_script[
            release_script.index(command) - 320 : release_script.index(command) + 320
        ]
        assert "BACKEND_RUNTIME_LOCK_RUNNER" in bat_command, command
        assert "BACKEND_RUNTIME_LOCK_RUNNER" in shell_command, command
        assert "BackendRuntimeLockRunner" in release_command, command

    server_command_index = run_dev_sh.index("run_server_background.py")
    assert "BACKEND_RUNTIME_LOCK_RUNNER" in run_dev_sh[
        server_command_index - 500 : server_command_index
    ]
    assert '"$PYTHON_BIN" - <<\'PY\'' not in run_dev_sh
    assert '"$PYTHON_BIN" src/scripts/run_frontend_background.py' not in run_dev_sh


def test_direct_backend_runtime_consumers_own_a_real_shared_os_lock():
    for source_path in (
        Path("src/scripts/build_backend_runtime.py"),
        Path("src/scripts/verify_backend_runtime.py"),
        Path("src/scripts/run_server_background.py"),
        Path("src/scripts/run_packaging_builds.py"),
    ):
        source = source_path.read_text(encoding="utf-8")
        assert "backend_runtime_lock" in source, source_path
        assert 'mode="shared"' in source, source_path
        assert "backend_runtime_lock_is_inherited" not in source, source_path


def test_macos_backend_environment_sync_precedes_state_based_resigning():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")
        sync_call = 'sync_backend_runtime_environment.py"'
        codesign_call = 'sign_macos_backend_runtime.py"'

        sync_index = launcher.index(sync_call)
        codesign_index = launcher.index(codesign_call, sync_index)
        assert sync_index < codesign_index
        assert "BACKEND_RUNTIME_STATE" in launcher
        assert "BACKEND_RUNTIME_CODESIGN_STAMP" in launcher
        assert '"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SIGNER"' in launcher
        assert "requirements_hash" not in launcher


def test_macos_backend_signing_is_owned_only_by_the_shared_python_cli():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")

        assert "sign_macos_backend_runtime.py" in launcher
        assert "codesign_macos_native_libraries()" not in launcher
        assert 'codesign --force --sign - "$native_library"' not in launcher
        assert 'shasum -a 256 "$BACKEND_RUNTIME_STATE"' not in launcher


def test_macos_backend_signing_finishes_before_target_venv_consumers_start():
    run_sh = Path("RUN.sh").read_text(encoding="utf-8")
    run_dev_sh = Path("RUN_DEV.sh").read_text(encoding="utf-8")

    run_sign_index = run_sh.index('"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SIGNER"')
    run_consumer_index = run_sh.index(
        '"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_LOCK_RUNNER"',
        run_sign_index,
    )
    dev_sign_index = run_dev_sh.index(
        '"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SIGNER"'
    )
    dev_consumer_index = run_dev_sh.index(
        '"$BOOTSTRAP_PYTHON" - "$BACKEND_RUNTIME_LOCK_RUNNER"',
        dev_sign_index,
    )

    assert run_sign_index < run_consumer_index
    assert dev_sign_index < dev_consumer_index


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
