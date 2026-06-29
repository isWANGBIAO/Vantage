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
set "BACKEND_RUNTIME_REQUIREMENTS_STAMP=%BACKEND_RUNTIME_VENV%\.requirements-backend-runtime-gpu.sha256"
set "WEBAPP_BUILD_INFO=%PROJECT_ROOT%src\webapp\build-info.json"
set "RUN_BUILD_INFO_BACKUP=%TEMP%\vantage-build-info-%RANDOM%-%RANDOM%.json"
set "BUILD_INFO_BACKUP_CREATED=0"
set "CUSTOM_NSIS_BINARY_RELEASE=1.0.0"
set "CUSTOM_NSIS_BINARY_FILE=nsisbi-electronbuilder-3.10.3.7z"
set "CUSTOM_NSIS_BINARY_URL=https://github.com/SoundSafari/NSISBI-ElectronBuilder/releases/download/%CUSTOM_NSIS_BINARY_RELEASE%/%CUSTOM_NSIS_BINARY_FILE%"
set "CUSTOM_NSIS_BINARY_SHA256=374cfc092fd1bd1898472df627549ecc165b0d6ba88e82deba085673aec95336"
if not defined VANTAGE_BUILD_WORKERS set "VANTAGE_BUILD_WORKERS=%NUMBER_OF_PROCESSORS%"
if not defined VANTAGE_ELECTRON_MIRROR_FALLBACK set "VANTAGE_ELECTRON_MIRROR_FALLBACK=https://npmmirror.com/mirrors/electron/"

call :CaptureSeconds RUN_START_SECONDS

call :StepStart "[0/7] Cleaning residual source processes..."
python src\scripts\cleanup_vantage_python_processes.py --include-desktop >nul 2>&1
call :StepDone "Source cleanup complete"

call :StepStart "[1/7] Checking frontend dependencies..."
if not exist "%PROJECT_ROOT%src\webapp\node_modules" (
    echo       Installing dependencies...
    pushd "%PROJECT_ROOT%src\webapp"
    call :RunNpmInstallWithFallback
    if errorlevel 1 (
        popd
        echo       npm install failed
        exit /b 1
    )
    popd
) else (
    echo       Dependencies already installed
)
pushd "%PROJECT_ROOT%src\webapp"
call :EnsureElectronBinary
if errorlevel 1 (
    popd
    echo       Electron binary preparation failed
    exit /b 1
)
popd
call :StepDone "Frontend dependency check complete"

call :StepStart "[2/7] Preparing backend packaging environment..."
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

for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%BACKEND_RUNTIME_REQUIREMENTS%').Hash"`) do set "BACKEND_RUNTIME_REQUIREMENTS_HASH=%%H"
set "BACKEND_RUNTIME_REQUIREMENTS_STORED_HASH="
if exist "%BACKEND_RUNTIME_REQUIREMENTS_STAMP%" (
    for /f "usebackq delims=" %%H in ("%BACKEND_RUNTIME_REQUIREMENTS_STAMP%") do set "BACKEND_RUNTIME_REQUIREMENTS_STORED_HASH=%%H"
)

set "BACKEND_RUNTIME_DEPS_NEED_SYNC=1"
if /I "!BACKEND_RUNTIME_REQUIREMENTS_HASH!"=="!BACKEND_RUNTIME_REQUIREMENTS_STORED_HASH!" if not "%VANTAGE_FORCE_BACKEND_DEPS%"=="1" set "BACKEND_RUNTIME_DEPS_NEED_SYNC=0"

if "!BACKEND_RUNTIME_DEPS_NEED_SYNC!"=="0" (
    echo       Backend runtime dependencies already synced
) else (
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
    > "%BACKEND_RUNTIME_REQUIREMENTS_STAMP%" echo !BACKEND_RUNTIME_REQUIREMENTS_HASH!
)
"%BACKEND_RUNTIME_PYTHON%" -c "import chinese_calendar, lap, zhdate; print('backend runtime dependency imports ok')"
if errorlevel 1 (
    echo       Backend runtime dependency import check failed
    exit /b 1
)
call :StepDone "Backend packaging environment ready"

call :StepStart "[3/8] Preparing build version..."
if exist "%WEBAPP_BUILD_INFO%" (
    copy /Y "%WEBAPP_BUILD_INFO%" "%RUN_BUILD_INFO_BACKUP%" >nul
    if errorlevel 1 (
        echo       Build version backup failed
        exit /b 1
    )
    set "BUILD_INFO_BACKUP_CREATED=1"
)
pushd "%PROJECT_ROOT%src\webapp"
call node scripts\prepare-build-version.mjs --mode auto
if errorlevel 1 (
    popd
    call :RestoreBuildInfo
    echo       Build version preparation failed
    exit /b 1
)
popd
call :StepDone "Build version prepared"

call :StepStart "[4/8] Building frontend and backend runtime in parallel..."
echo       Build workers requested: %VANTAGE_BUILD_WORKERS%
"%BACKEND_RUNTIME_PYTHON%" src\scripts\run_packaging_builds.py --backend-python "%BACKEND_RUNTIME_PYTHON%" --workers "%VANTAGE_BUILD_WORKERS%"
if errorlevel 1 (
    call :RestoreBuildInfo
    echo       Parallel packaging build failed
    exit /b 1
)
call :StepDone "Frontend and backend build step complete"

call :StepStart "[5/8] Verifying backend runtime..."
"%BACKEND_RUNTIME_PYTHON%" src\scripts\verify_backend_runtime.py --timeout-seconds 60
if errorlevel 1 (
    call :RestoreBuildInfo
    echo       Backend runtime verification failed
    exit /b 1
)
call :StepDone "Backend runtime verification complete"

call :StepStart "[6/8] Building Windows installer..."
call :EnsureCustomNsisArchiveCache
if errorlevel 1 (
    call :RestoreBuildInfo
    echo       Custom NSIS archive cache preparation failed
    exit /b 1
)
pushd "%PROJECT_ROOT%src\webapp"
call :RunElectronPackageWithFallback
if errorlevel 1 (
    popd
    call :RestoreBuildInfo
    echo       Installer build failed
    exit /b 1
)
popd
call :RestoreBuildInfo
call :StepDone "Windows installer build complete"

call :StepStart "[7/8] Preparing silent install..."
powershell -NoProfile -ExecutionPolicy Bypass -Command "$targets = Get-ChildItem -Path '%STARTUP_FOLDER%' -Filter 'RUN.bat*.lnk' -ErrorAction SilentlyContinue; if ($targets) { $targets | Remove-Item -Force; Write-Host '      Removed startup shortcut residue' } else { Write-Host '      No startup shortcut residue found' }"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$installer = Get-ChildItem -Path '%PROJECT_ROOT%src\\webapp\\electron-dist' -Filter 'Vantage Setup *.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($installer) { $installer.FullName }"`) do set "INSTALLER_PATH=%%I"

if not defined INSTALLER_PATH (
    echo       Installer package not found in src\webapp\electron-dist
    exit /b 1
)

echo       Latest installer: %INSTALLER_PATH%
taskkill /IM Vantage.exe /F >nul 2>&1
taskkill /IM VantageBackend.exe /F >nul 2>&1
call :StepDone "Silent install prepared"

call :StepStart "[8/8] Installing and launching Vantage..."
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
call :StepDone "Install and launch command complete"

call :CaptureSeconds RUN_END_SECONDS
set /a TOTAL_DURATION_SECONDS=RUN_END_SECONDS-RUN_START_SECONDS

echo.
echo ========================================
echo    Build, install, and launch complete
echo    Total elapsed: !TOTAL_DURATION_SECONDS!s
echo ========================================

exit /b 0

:CaptureSeconds
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[DateTimeOffset]::Now.ToUnixTimeSeconds()"`) do set "%~1=%%T"
exit /b 0

:StepStart
call :CaptureSeconds STEP_START_SECONDS
echo %~1
exit /b 0

:StepDone
call :CaptureSeconds STEP_END_SECONDS
set /a STEP_DURATION_SECONDS=STEP_END_SECONDS-STEP_START_SECONDS
echo       %~1 (!STEP_DURATION_SECONDS!s)
exit /b 0

:UseElectronMirrorFallback
if defined ELECTRON_MIRROR (
    echo       ELECTRON_MIRROR already set: !ELECTRON_MIRROR!
) else (
    set "ELECTRON_MIRROR=%VANTAGE_ELECTRON_MIRROR_FALLBACK%"
    echo       Retrying Electron download with mirror fallback: !ELECTRON_MIRROR!
)
exit /b 0

:RunNpmInstallWithFallback
call npm install
if not errorlevel 1 exit /b 0
if defined ELECTRON_MIRROR exit /b 1
call :UseElectronMirrorFallback
call npm install
exit /b %ERRORLEVEL%

:EnsureElectronBinary
call node node_modules\electron\install.js
if not errorlevel 1 goto VerifyElectronBinary
if defined ELECTRON_MIRROR exit /b 1
call :UseElectronMirrorFallback
call node node_modules\electron\install.js
if errorlevel 1 exit /b 1
:VerifyElectronBinary
call npm exec -- electron --version
exit /b %ERRORLEVEL%

:RunElectronPackageWithFallback
call npm run electron:package
if not errorlevel 1 exit /b 0
if defined ELECTRON_MIRROR exit /b 1
call :UseElectronMirrorFallback
call npm run electron:package
exit /b %ERRORLEVEL%

:EnsureCustomNsisArchiveCache
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $override = $env:ELECTRON_BUILDER_CACHE; if ($override -and [System.IO.Path]::IsPathRooted($override)) { $cacheRoot = $override } elseif ($env:LOCALAPPDATA) { $cacheRoot = Join-Path $env:LOCALAPPDATA 'electron-builder\Cache' } else { $cacheRoot = Join-Path $env:TEMP 'electron-builder-cache' }; $archiveDir = Join-Path $cacheRoot '%CUSTOM_NSIS_BINARY_RELEASE%'; $archive = Join-Path $archiveDir '%CUSTOM_NSIS_BINARY_FILE%'; $expected = '%CUSTOM_NSIS_BINARY_SHA256%'; if (Test-Path -LiteralPath $archive) { $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant(); if ($actual -eq $expected) { Write-Host '      Custom NSIS archive cache ready'; exit 0 }; Write-Host '      Custom NSIS archive checksum mismatch; refreshing'; Remove-Item -LiteralPath $archive -Force }; New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null; $tmp = $archive + '.tmp'; if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }; & curl.exe --silent --show-error --location --retry 3 --retry-delay 2 --fail --output $tmp '%CUSTOM_NSIS_BINARY_URL%'; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tmp).Hash.ToLowerInvariant(); if ($actual -ne $expected) { Remove-Item -LiteralPath $tmp -Force; throw 'Custom NSIS archive checksum mismatch' }; Move-Item -LiteralPath $tmp -Destination $archive -Force; Write-Host '      Custom NSIS archive cache ready'"
exit /b %ERRORLEVEL%

:RestoreBuildInfo
if "%BUILD_INFO_BACKUP_CREATED%"=="1" if exist "%RUN_BUILD_INFO_BACKUP%" (
    copy /Y "%RUN_BUILD_INFO_BACKUP%" "%WEBAPP_BUILD_INFO%" >nul
    del "%RUN_BUILD_INFO_BACKUP%" >nul 2>&1
    set "BUILD_INFO_BACKUP_CREATED=0"
    echo       Source build-info restored
)
exit /b 0
