@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
echo.
echo MELB Nutrition is restarting...
echo Any existing MELB server from this folder will be replaced.
echo PC:    http://127.0.0.1:8501
echo Phone: keep using your existing MELB address.
echo.
echo Keep this window open while you use the app.
echo Press Ctrl+C to stop it.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0START_MELB_BACKGROUND.py" --restart --foreground
pause
