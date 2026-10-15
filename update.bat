@echo off
REM Pulls the latest code from GitHub and restarts the app. Client data (data\clients) is never touched.
setlocal
cd /d "%~dp0"
set GIT=git
where git >nul 2>nul || (
  if exist "%ProgramFiles%\Git\cmd\git.exe" (set "GIT=%ProgramFiles%\Git\cmd\git.exe") else (
  if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" (set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe") else (
  echo git not found - install from https://git-scm.com/download/win & pause & exit /b 1)))
echo === %date% %time% update.bat >> update.log
taskkill /f /im pythonw.exe >nul 2>nul
set GIT_TERMINAL_PROMPT=0
"%GIT%" pull --ff-only
echo pull exit %errorlevel% >> update.log
"%GIT%" log -1 --format=%%h_%%s >> update.log 2>&1
if errorlevel 1 (echo update failed - see update.log & pause)
call run.bat
