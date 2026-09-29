@echo off
setlocal
set "VANTAGE_BACKEND=%~dp0..\backend-runtime\VantageBackend\VantageBackend.exe"
if not exist "%VANTAGE_BACKEND%" (
  >&2 echo Vantage backend runtime was not found. Repair or reinstall Vantage.
  exit /b 1
)
"%VANTAGE_BACKEND%" --run-cli %*
exit /b %errorlevel%
