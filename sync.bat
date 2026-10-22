@echo off
REM ייבוא לקוחות מתיקיית איסוף – לסקריפט החילוץ מריווחית (אותה פעולה כמו הכפתור "ייבוא מתיקייה" בתוכנה).
REM שימוש:  sync.bat "C:\Users\U\Desktop\איסוף דוחות"            ייבוא של כל מה שחדש / השתנה
REM         sync.bat "C:\...\איסוף דוחות" --dry-run              רק להציג מה יקרה
REM         sync.bat "C:\...\איסוף דוחות" --client "גלגש הנדסה בעמ"   רק לקוח אחד
REM תוצאה: מודפסת, ונשמרת גם ב-<תיקיית הנתונים>\sync_reports\
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo The app is not installed yet - run run.bat once first.
  exit /b 1
)
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m trapped_profits.folder_import %*
exit /b %ERRORLEVEL%
