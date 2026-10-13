@echo off
REM Starts the trapped-profits app on Windows. Double-click to run.
REM Needs Python 3.10+ from python.org. Works whether or not "Add to PATH" was ticked (falls back to the py launcher).
setlocal
cd /d "%~dp0"
echo === %date% %time% === >> setup.log

set PY=
where python >nul 2>nul && python -c "import sys" >nul 2>nul && set PY=python
if "%PY%"=="" where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (
  echo Python not found. Install it from https://www.python.org/downloads/windows/ and run again.
  pause & exit /b 1
)
echo using %PY% >> setup.log

if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv >> setup.log 2>&1 || (echo venv failed - see setup.log & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q >> setup.log 2>&1
python -m pip install -r requirements.txt -q >> setup.log 2>&1 || (echo pip install failed - see setup.log & pause & exit /b 1)
echo deps ok >> setup.log

start "" /b pythonw app.py
exit /b 0
