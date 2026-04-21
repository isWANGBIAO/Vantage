@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo    Vantage - Electron Launcher
echo ========================================
echo.

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
set "ELECTRON_RUN_AS_NODE="
set "BACKEND_STATUS_URL=http://127.0.0.1:8000/api/status"
set "BACKEND_WAIT_TIMEOUT=60"
set "SERVER_LATEST_POINTER=%PROJECT_ROOT%logs\server.latest.log"

echo [0/3] Cleaning residual processes...

python src\scripts\cleanup_vantage_python_processes.py --include-desktop >nul 2>&1

echo       Cleanup complete
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"

echo [1/3] Starting backend...

if not exist "%PROJECT_ROOT%logs" mkdir "%PROJECT_ROOT%logs"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath python -ArgumentList 'src/scripts/run_server_background.py' -WorkingDirectory '%PROJECT_ROOT%' -WindowStyle Hidden"

echo       Waiting for backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$elapsed = 0; while ($elapsed -lt %BACKEND_WAIT_TIMEOUT%) { try { $response = Invoke-WebRequest -Uri '%BACKEND_STATUS_URL%' -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { $status = $response.Content | ConvertFrom-Json; if ($status.camera_online) { Write-Host '      Backend ready (camera online)' } else { Write-Host '      Backend ready (camera offline)' }; exit 0 } } catch { }; $elapsed += 1; Write-Host ('      Waiting for backend... ' + $elapsed + '/%BACKEND_WAIT_TIMEOUT%s'); Start-Sleep -Seconds 1 }; Write-Host '      Backend did not become ready within %BACKEND_WAIT_TIMEOUT% seconds'; try { $response = Invoke-WebRequest -Uri '%BACKEND_STATUS_URL%' -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { Write-Host '      Latest /api/status:'; Write-Host $response.Content } } catch { Write-Host ('      Final status check failed: ' + $_.Exception.Message) }; $latestLogPath = $null; if (Test-Path '%SERVER_LATEST_POINTER%') { try { $candidate = (Get-Content '%SERVER_LATEST_POINTER%' -ErrorAction Stop | Select-Object -First 1).Trim(); if ($candidate -and (Test-Path $candidate)) { $latestLogPath = $candidate } } catch { } }; if (-not $latestLogPath) { $serverLogDir = Join-Path '%PROJECT_ROOT%logs' 'server'; if (Test-Path $serverLogDir) { $latestFile = Get-ChildItem $serverLogDir -Filter 'server-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($latestFile) { $latestLogPath = $latestFile.FullName } } }; if ($latestLogPath) { Write-Host ('      Last 20 lines of ' + $latestLogPath + ':'); Get-Content $latestLogPath -Tail 20 }; exit 1"
if errorlevel 1 exit /b 1

echo [2/3] Checking frontend dependencies...
if not exist "%PROJECT_ROOT%src\webapp\node_modules" (
    echo       Installing dependencies...
    cd /d "%PROJECT_ROOT%src\webapp"
    call npm install
) else (
    echo       Dependencies already installed
)

echo [3/3] Launching Electron...
cd /d "%PROJECT_ROOT%src\webapp"

echo       Checking frontend build state...
node check_build.js
if %errorlevel% neq 0 (
    echo       Build required, running npm run build...
    call npm run build
) else (
    echo       Build is up to date
)

if exist "%PROJECT_ROOT%src\webapp\dist\index.html" (
    echo       Starting production Electron app in background...
    cd /d "%PROJECT_ROOT%"
    python src\scripts\run_frontend_background.py production
) else (
    echo       Starting development Electron app in background...
    cd /d "%PROJECT_ROOT%"
    python src\scripts\run_frontend_background.py development
)

echo.
echo ========================================
echo    Application launched in background
echo ========================================
