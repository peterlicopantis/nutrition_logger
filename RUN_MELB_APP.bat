@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
echo.
echo MELB Nutrition is starting...
echo PC:    http://127.0.0.1:8501
echo Phone: use this PC's local IP or Tailscale IP, followed by :8501
echo.
echo Keep this window open while you use the app.
echo Press Ctrl+C to stop it.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
pause
