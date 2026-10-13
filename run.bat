@echo off
REM Starts the trapped-profits app on Windows. Double-click to run.
REM Needs Python 3.10+ from python.org (tick "Add python.exe to PATH" when installing).
setlocal
cd /d "%~dp0"
echo === %date% %time% === >> setup.log

where python >nul 2>nul || (
  echo Python not found. Install it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  pause & exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv >> setup.log 2>&1 || (echo venv failed - see setup.log & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q >> setup.log 2>&1
python -m pip install -r requirements.txt -q >> setup.log 2>&1 || (echo pip install failed - see setup.log & pause & exit /b 1)
echo deps ok >> setup.log

start "" /b pythonw app.py
exit /b 0
