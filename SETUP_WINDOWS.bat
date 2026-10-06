@echo off
setlocal
cd /d "%~dp0"
echo Creating Python environment...
py -3 -m venv .venv
if errorlevel 1 (
  echo.
  echo Could not find Python via the "py" launcher.
  echo Install Python 3.11 or newer from python.org, then run this again.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Setup complete.
echo Double-click RUN_MELB_APP.bat to start the app.
pause
