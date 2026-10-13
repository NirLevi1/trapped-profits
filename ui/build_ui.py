"""מייצר מהתבנית את שני הקבצים:
  ui/index.html        – הממשק של התוכנה (מסמך מלא, ללא נתוני דמו)
  dashboard/index.html – תצוגת דפדפן עם לקוחות הדמו (לפרסום כעמוד)

הרצה: python ui/build_ui.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = (ROOT / "ui" / "_template.html").read_text(encoding="utf-8")


def strip_markers(s: str, *names: str) -> str:
    for n in names:
        s = re.sub(rf"<!--{n}-->.*?<!--/{n}-->\n?", "", s, flags=re.S)
    return s


def seed_records() -> list[dict]:
    out = []
    for f in sorted((ROOT / "examples" / "reports").glob("*.json")):
        if f.name.startswith("_"):
            continue
        res = json.loads(f.read_text(encoding="utf-8"))
        inp = json.loads((ROOT / "examples" / "clients" / f.name).read_text(encoding="utf-8"))
        i = len(out) + 1
        out.append({"id": f"demo{i}", "input": inp, "result": res, "error": None,
                    "updated_at": "2026-10-13T12:00:00", "created_at": "2026-10-07T18:00:00",
                    "logic_version": res["logic_version"], "stale": i == 4,
                    "handling": {"status": ["טרם טופל", "בשיחה", "הוחלט: חלוקה"][i % 3], "note": "", "at": None}})
    return out


def main() -> None:
    # 1. התוכנה: מסמך מלא, בלי דמו
    app = re.sub(r"<!--HEAD_START-->\n|<!--HEAD_END-->\n|<!--BODY_OPEN-->\n|<!--/BODY_OPEN-->\n|<!--BODY_CLOSE-->\n|<!--/BODY_CLOSE-->\n", "", TPL)
    (ROOT / "ui" / "index.html").write_text(app, encoding="utf-8")

    # 2. תצוגת דפדפן: בלי שלד המסמך (העמוד מקבל שלד בפרסום), עם דמו
    web = re.sub(r"<!--HEAD_START-->.*?<!--HEAD_END-->\n", "", TPL, flags=re.S)
    web = strip_markers(web, "BODY_OPEN", "BODY_CLOSE")
    web = web.replace("/*SEED*/[]/*/SEED*/", json.dumps(seed_records(), ensure_ascii=False))
    (ROOT / "dashboard").mkdir(exist_ok=True)
    (ROOT / "dashboard" / "index.html").write_text(web, encoding="utf-8")
    print("ok", file=sys.stderr)


if __name__ == "__main__":
    main()
