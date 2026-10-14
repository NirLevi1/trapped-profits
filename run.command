#!/bin/bash
# הפעלת תוכנת הרווחים הכלואים במק – לחיצה כפולה מריצה
cd "$(dirname "$0")"
LOG=setup.log
{
  echo "=== $(date) ==="
  if [ ! -d .venv ]; then python3 -m venv .venv || exit 1; fi
  source .venv/bin/activate
  python3 -m pip install --upgrade pip -q
  python3 -m pip install -r requirements.txt -q || exit 1
  echo "deps ok"
  # זיהוי תווים לדוח שנתי סרוק – מותקן פעם אחת דרך ברו אם יש
  if ! command -v tesseract >/dev/null 2>&1 && [ ! -x tesseract/tesseract ]; then
    if command -v brew >/dev/null 2>&1; then echo "installing tesseract via brew"; brew install tesseract || echo "brew install tesseract failed – scanned PDFs will not be read"; fi
  fi
  python3 app.py
} 2>&1 | tee -a "$LOG"
