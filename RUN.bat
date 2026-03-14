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

echo [0/3] Cleaning residual processes...

taskkill /F /IM electron.exe >nul 2>&1

for /f "tokens=5" %%a in ('netstat -aon ^| find ":5173" ^| find "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

python src\scripts\cleanup_vantage_python_processes.py >nul 2>&1

echo       Cleanup complete
timeout /t 2 /nobreak >nul

echo [1/3] Starting backend...

if not exist "%PROJECT_ROOT%logs" mkdir "%PROJECT_ROOT%logs"
start "Vantage Backend" /min cmd /c "cd /d %PROJECT_ROOT% && python src/server.py > logs/server.log 2>&1"

echo       Waiting for backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$elapsed = 0; while ($elapsed -lt %BACKEND_WAIT_TIMEOUT%) { try { $response = Invoke-WebRequest -Uri '%BACKEND_STATUS_URL%' -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { Write-Host '      Backend ready'; exit 0 } } catch { }; $elapsed += 1; Write-Host ('      Waiting for backend... ' + $elapsed + '/%BACKEND_WAIT_TIMEOUT%s'); Start-Sleep -Seconds 1 }; Write-Host '      Backend did not become ready within %BACKEND_WAIT_TIMEOUT% seconds'; if (Test-Path '%PROJECT_ROOT%logs\server.log') { Write-Host '      Last 20 lines of logs\server.log:'; Get-Content '%PROJECT_ROOT%logs\server.log' -Tail 20 }; exit 1"
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
    echo       Starting production Electron app...
    set "NODE_ENV=production"
    call npm run electron:start
) else (
    echo       Starting development Electron app...
    call npm run electron:dev
)

echo.
echo ========================================
echo    Application closed
echo ========================================
