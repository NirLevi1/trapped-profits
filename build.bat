@echo off
REM Builds a single portable TrappedProfits.exe into the "dist" folder.
REM Run on any Windows PC with Python 3.10+ installed (python.org, tick "Add to PATH").
setlocal
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :fail

echo Building TrappedProfits.exe ...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name TrappedProfits ^
  --hidden-import openpyxl ^
  --collect-all webview ^
  --add-data "ui;ui" ^
  app.py || goto :fail

echo.
echo Done!  The app is at:  %cd%\dist\TrappedProfits.exe
echo Client data is saved next to the exe in data\clients.
pause
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
