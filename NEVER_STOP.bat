@echo off
setlocal
cd /d "%~dp0"
if not exist "src\webapp\node_modules\electron\dist\electron.exe" (
  echo Installing desktop dependencies...
  call npm --prefix src\webapp ci
  if errorlevel 1 exit /b 1
)
call npm --prefix src\webapp run never-stop:build
if errorlevel 1 exit /b 1
set ELECTRON_RUN_AS_NODE=
start "Never Stop" "src\webapp\node_modules\electron\dist\electron.exe" "src\webapp\never-stop\main.cjs"
