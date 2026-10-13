@echo off
REM Pulls the latest code from GitHub and restarts the app. Client data (data\clients) is never touched.
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo git not found - install from https://git-scm.com/download/win & pause & exit /b 1)
taskkill /f /im pythonw.exe >nul 2>nul
git pull --ff-only || (echo update failed & pause & exit /b 1)
call run.bat
