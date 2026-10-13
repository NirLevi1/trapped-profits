@echo off
REM One-click installer for the trapped-profits app on Windows.
REM Installs Python and Git if missing (via winget), clones the code to %USERPROFILE%\trapped-profits and starts the app.
REM Safe to run again: if the folder already exists it just updates and starts.
setlocal
set TARGET=%USERPROFILE%\trapped-profits
set REPO=https://github.com/NirLevi1/trapped-profits

echo.
echo  ==== Fortera - Trapped Profits - install ====
echo.

where winget >nul 2>nul || (
  echo winget not found. Install Python 3.12 from python.org and Git from git-scm.com, then run this file again.
  pause & exit /b 1
)

REM ---- Python
set HAVEPY=
where py >nul 2>nul && set HAVEPY=1
where python >nul 2>nul && python -c "import sys" >nul 2>nul && set HAVEPY=1
if not defined HAVEPY (
  echo Installing Python 3.12 ...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent || (echo Python install failed & pause & exit /b 1)
)

REM ---- Git
where git >nul 2>nul || (
  echo Installing Git ...
  winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements --silent || (echo Git install failed & pause & exit /b 1)
)

REM ---- refresh PATH for this window (new installs are not visible to the current cmd otherwise)
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%b"
set "PATH=%SYSPATH%;%USRPATH%;%PATH%"

where git >nul 2>nul || (echo Git still not found - close this window, open a new cmd and run install.bat again. & pause & exit /b 1)

REM ---- code
if exist "%TARGET%\.git" (
  echo Updating existing installation ...
  cd /d "%TARGET%" && git pull --ff-only
) else (
  echo Downloading the app ...
  git clone %REPO% "%TARGET%" || (echo clone failed & pause & exit /b 1)
  cd /d "%TARGET%"
)

echo Starting ...
call run.bat
echo.
echo Done. Next time: double-click run.bat in %TARGET%
echo (update.bat there pulls the latest version)
pause
