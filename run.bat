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

REM ---- Auto-update: pull the latest code from GitHub when online (data\ is never touched). Offline -> just runs.
if exist .git (
  set GIT=
  where git >nul 2>nul && set GIT=git
  if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
  if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
  if defined GIT (
    echo checking for updates... >> setup.log
    set GIT_TERMINAL_PROMPT=0
    "%GIT%" pull --ff-only --quiet >> setup.log 2>&1 && echo up to date >> setup.log || echo update skipped (offline or local change) >> setup.log
  ) else (echo git not found - no auto update >> setup.log)
)

if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv >> setup.log 2>&1 || (echo venv failed - see setup.log & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q >> setup.log 2>&1
python -m pip install -r requirements.txt -q >> setup.log 2>&1 || (echo pip install failed - see setup.log & pause & exit /b 1)
echo deps ok >> setup.log

REM Desktop shortcut with the Fortera icon (created once)
if not exist "%USERPROFILE%\Desktop\Fortera - Trapped Profits.lnk" (
  powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Fortera - Trapped Profits.lnk');$s.TargetPath='%CD%\run.bat';$s.WorkingDirectory='%CD%';$s.IconLocation='%CD%\assets\icon.ico';$s.Description='Fortera - trapped profits';$s.WindowStyle=7;$s.Save()" >> setup.log 2>&1
)

start "" /b pythonw app.py
exit /b 0
