@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo    Vantage - Build and Install
echo ========================================
echo.

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
set "INSTALL_ROOT=%LOCALAPPDATA%\Programs\Vantage"
set "INSTALLED_EXE=%INSTALL_ROOT%\Vantage.exe"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "BACKEND_RUNTIME_VENV=%PROJECT_ROOT%.venv-backend-runtime-gpu"
set "BACKEND_RUNTIME_PYTHON=%BACKEND_RUNTIME_VENV%\Scripts\python.exe"
set "BACKEND_RUNTIME_REQUIREMENTS=%PROJECT_ROOT%requirements-backend-runtime-gpu.txt"

echo [0/7] Cleaning residual source processes...
python src\scripts\cleanup_vantage_python_processes.py --include-desktop >nul 2>&1
echo       Source cleanup complete

echo [1/7] Checking frontend dependencies...
if not exist "%PROJECT_ROOT%src\webapp\node_modules" (
    echo       Installing dependencies...
    pushd "%PROJECT_ROOT%src\webapp"
    call npm install
    if errorlevel 1 (
        popd
        echo       npm install failed
        exit /b 1
    )
    popd
) else (
    echo       Dependencies already installed
)

echo [2/7] Preparing backend packaging environment...
if not exist "%BACKEND_RUNTIME_PYTHON%" (
    echo       Creating clean backend runtime venv...
    python -m venv "%BACKEND_RUNTIME_VENV%"
    if errorlevel 1 (
        echo       Backend runtime venv creation failed
        exit /b 1
    )
) else (
    echo       Backend runtime venv already exists
)

echo       Syncing backend runtime dependencies...
"%BACKEND_RUNTIME_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo       Backend runtime pip upgrade failed
    exit /b 1
)
"%BACKEND_RUNTIME_PYTHON%" -m pip install -r "%BACKEND_RUNTIME_REQUIREMENTS%"
if errorlevel 1 (
    echo       Backend runtime dependency install failed
    exit /b 1
)

echo [3/7] Building backend runtime...
"%BACKEND_RUNTIME_PYTHON%" src\scripts\build_backend_runtime.py
if errorlevel 1 (
    echo       Backend runtime build failed
    exit /b 1
)

echo [4/7] Verifying backend runtime...
"%BACKEND_RUNTIME_PYTHON%" src\scripts\verify_backend_runtime.py --timeout-seconds 60
if errorlevel 1 (
    echo       Backend runtime verification failed
    exit /b 1
)

echo [5/7] Building Windows installer...
pushd "%PROJECT_ROOT%src\webapp"
call npm run electron:build
if errorlevel 1 (
    popd
    echo       Installer build failed
    exit /b 1
)
popd

echo [6/7] Preparing silent install...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$targets = Get-ChildItem -Path '%STARTUP_FOLDER%' -Filter 'RUN.bat*.lnk' -ErrorAction SilentlyContinue; if ($targets) { $targets | Remove-Item -Force; Write-Host '      Removed startup shortcut residue' } else { Write-Host '      No startup shortcut residue found' }"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$installer = Get-ChildItem -Path '%PROJECT_ROOT%src\\webapp\\electron-dist' -Filter 'Vantage Setup *.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($installer) { $installer.FullName }"`) do set "INSTALLER_PATH=%%I"

if not defined INSTALLER_PATH (
    echo       Installer package not found in src\webapp\electron-dist
    exit /b 1
)

echo       Latest installer: %INSTALLER_PATH%
taskkill /IM Vantage.exe /F >nul 2>&1
taskkill /IM VantageBackend.exe /F >nul 2>&1

echo [7/7] Installing and launching Vantage...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$process = Start-Process -FilePath '%INSTALLER_PATH%' -ArgumentList '/S' -Wait -PassThru; exit $process.ExitCode"
if errorlevel 1 (
    echo       Silent installer failed
    exit /b 1
)

if not exist "%INSTALLED_EXE%" (
    echo       Installed executable not found: %INSTALLED_EXE%
    exit /b 1
)

start "" "%INSTALLED_EXE%"

echo.
echo ========================================
echo    Build, install, and launch complete
echo ========================================
