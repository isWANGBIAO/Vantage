@echo off
echo Starting AI Manager WebApp...

:: Check if node_modules exists
if not exist "webapp\node_modules" (
    echo Installing frontend dependencies...
    cd webapp
    call npm install
    cd ..
)

:: Start Backend
start "Backend Server" cmd /k "python src/server.py"

:: Start Frontend
cd webapp
start "Frontend Server" cmd /k "npm run dev"

echo WebApp starting... Please browse to http://localhost:5173
echo (Note: Backend is on port 8000)
pause
