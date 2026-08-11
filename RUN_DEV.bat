@echo off
chcp 65001 >nul
setlocal

echo ========================================
echo    Vantage - Development Launcher
echo ========================================
echo.

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT_ARG=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"
set "ELECTRON_RUN_AS_NODE="
set "BOOTSTRAP_PYTHON=python"
set "BACKEND_RUNTIME_VENV=%PROJECT_ROOT%.venv-backend-runtime-gpu"
set "BACKEND_RUNTIME_PYTHON=%BACKEND_RUNTIME_VENV%\Scripts\python.exe"
set "BACKEND_RUNTIME_CORE_REQUIREMENTS=%PROJECT_ROOT%requirements-core.txt"
set "BACKEND_RUNTIME_REQUIREMENTS=%PROJECT_ROOT%requirements-backend-runtime-gpu.txt"
set "OPENCV_NORMALIZER=%PROJECT_ROOT%src\scripts\normalize_opencv_installation.py"
set "BACKEND_RUNTIME_SYNC=%PROJECT_ROOT%src\scripts\sync_backend_runtime_environment.py"
set "BACKEND_RUNTIME_LOCK_RUNNER=%PROJECT_ROOT%src\scripts\run_with_backend_runtime_lock.py"
set "BACKEND_RUNTIME_BACKGROUND_LAUNCHER=%PROJECT_ROOT%src\scripts\launch_locked_backend_background.py"
set "FRONTEND_ROOT=%PROJECT_ROOT%src\webapp"
set "BACKEND_STATUS_URL=http://127.0.0.1:8000/api/status"
set "BACKEND_WAIT_TIMEOUT=60"
set "SERVER_LATEST_POINTER=%PROJECT_ROOT%logs\server.latest.log"

echo [0/4] Cleaning residual processes...
set "CLEANUP_PYTHON=%BOOTSTRAP_PYTHON%"
if exist "%BACKEND_RUNTIME_PYTHON%" set "CLEANUP_PYTHON=%BACKEND_RUNTIME_PYTHON%"
"%BOOTSTRAP_PYTHON%" "%BACKEND_RUNTIME_LOCK_RUNNER%" --project-root "%PROJECT_ROOT_ARG%" -- "%CLEANUP_PYTHON%" src\scripts\cleanup_vantage_python_processes.py --include-desktop >nul 2>&1
echo       Cleanup complete
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"

echo [1/4] Preparing the dedicated backend environment...
set "BACKEND_RUNTIME_SYNC_FORCE_ARG="
if "%VANTAGE_FORCE_BACKEND_DEPS%"=="1" set "BACKEND_RUNTIME_SYNC_FORCE_ARG=--force"
"%BOOTSTRAP_PYTHON%" "%BACKEND_RUNTIME_SYNC%" --project-root "%PROJECT_ROOT_ARG%" --venv "%BACKEND_RUNTIME_VENV%" --core-requirements "%BACKEND_RUNTIME_CORE_REQUIREMENTS%" --requirements "%BACKEND_RUNTIME_REQUIREMENTS%" --opencv-normalizer "%OPENCV_NORMALIZER%" %BACKEND_RUNTIME_SYNC_FORCE_ARG%
if errorlevel 1 (
    echo       Backend runtime environment synchronization failed
    exit /b 1
)

echo [2/4] Starting the locked backend...
if not exist "%PROJECT_ROOT%logs" mkdir "%PROJECT_ROOT%logs"
"%BOOTSTRAP_PYTHON%" "%BACKEND_RUNTIME_BACKGROUND_LAUNCHER%" --project-root "%PROJECT_ROOT_ARG%" --lock-runner "%BACKEND_RUNTIME_LOCK_RUNNER%" --backend-python "%BACKEND_RUNTIME_PYTHON%"
if errorlevel 1 (
    echo       Backend launch failed
    exit /b 1
)

echo       Waiting for backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$elapsed = 0; while ($elapsed -lt [int]$env:BACKEND_WAIT_TIMEOUT) { try { $response = Invoke-WebRequest -Uri $env:BACKEND_STATUS_URL -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { $status = $response.Content | ConvertFrom-Json; if ($status.camera_online) { Write-Host '      Backend ready (camera online)' } else { Write-Host '      Backend ready (camera offline)' }; exit 0 } } catch { }; $elapsed += 1; Write-Host ('      Waiting for backend... ' + $elapsed + '/' + $env:BACKEND_WAIT_TIMEOUT + 's'); Start-Sleep -Seconds 1 }; Write-Host ('      Backend did not become ready within ' + $env:BACKEND_WAIT_TIMEOUT + ' seconds'); $latestLogPath = $null; if (Test-Path -LiteralPath $env:SERVER_LATEST_POINTER) { try { $candidate = (Get-Content -LiteralPath $env:SERVER_LATEST_POINTER -ErrorAction Stop | Select-Object -First 1).Trim(); if ($candidate) { if ([System.IO.Path]::IsPathRooted($candidate)) { $resolved = $candidate } else { $resolved = Join-Path $env:PROJECT_ROOT $candidate }; if (Test-Path -LiteralPath $resolved) { $latestLogPath = $resolved } } } catch { } }; if ($latestLogPath) { Write-Host '      Last 20 backend log lines:'; Get-Content -LiteralPath $latestLogPath -Tail 20 }; exit 1"
if errorlevel 1 exit /b 1

echo [3/4] Synchronizing frontend dependencies...
call node "%FRONTEND_ROOT%\scripts\sync-dependencies.cjs" --webapp-root "%FRONTEND_ROOT%"
if errorlevel 1 (
    echo       Frontend dependency synchronization failed
    exit /b 1
)

echo [4/4] Launching Electron...
pushd "%FRONTEND_ROOT%"
call node check_build.js
if errorlevel 1 (
    echo       Build required, running npm run build...
    call npm run build
    if errorlevel 1 (
        popd
        echo       Frontend build failed
        exit /b 1
    )
) else (
    echo       Build is up to date
)
popd

if exist "%FRONTEND_ROOT%\dist\index.html" (
    echo       Starting production Electron app in background...
    "%BOOTSTRAP_PYTHON%" src\scripts\run_frontend_background.py production
) else (
    echo       Starting development Electron app in background...
    "%BOOTSTRAP_PYTHON%" src\scripts\run_frontend_background.py development
)
if errorlevel 1 exit /b 1

echo.
echo ========================================
echo    Development app launched in background
echo ========================================
exit /b 0
