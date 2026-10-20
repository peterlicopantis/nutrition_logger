@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ENABLE_CAMERA_HTTPS.ps1"
set "melbExitCode=%errorlevel%"
pause
exit /b %melbExitCode%
