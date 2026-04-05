@echo off
echo Starting Vantage WebApp...
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

:: Check if node_modules exists
if not exist "src\webapp\node_modules" (
    echo Installing frontend dependencies...
    cd src\webapp
    call npm install
    cd ..\..
)

:: Start Backend
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath python -ArgumentList 'src/scripts/run_server_background.py' -WorkingDirectory '%PROJECT_ROOT%' -WindowStyle Hidden"

:: Start Frontend
cd src\webapp
start "Frontend Server" cmd /k "npm run dev"

echo WebApp starting... Please browse to http://localhost:5173
echo (Note: Backend is on port 8000)
pause
