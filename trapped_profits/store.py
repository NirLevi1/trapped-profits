"""אחסון לקוחות: קובץ JSON לכל לקוח בתיקיית data/clients ליד התוכנה.

כל קובץ: {"id", "input", "result", "updated_at", "logic_version"}.
שמירה = חישוב מיידי. היסטוריית שינויים – משימה פתוחה (כרגע מצב נוכחי + חותמת זמן).
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import LOGIC_VERSION, compute
from .models import ClientInput
from .report import render_markdown


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_KEYS = {
    "סטטוס כולל": ("dashboard", "status_overall"),
    "תוספת מס": ("calc81", "surtax"),
    "פער לחלוקה": ("simulator", "gap_to_close"),
    "שכר לתיקון 62א": ("s62a", "attributed_income"),
    "מוגן עד": ("dashboard", "protected_until"),
}


def _normalize_date(s: str) -> str:
    """'נכון ל-' בכל פורמט נפוץ (30.9.2026, 30/09/2026, 2026-09-30) → ISO; טקסט לא מזוהה נשאר כמו שהוא."""
    s = str(s).strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _is_stale(rec: dict, stale_days: int) -> bool:
    """החלטה 15: נתוני הלקוח ישנים מ-N ימים (לפי 'נכון ל-', ואם אין – לפי מועד העדכון)."""
    src = (rec.get("input") or {}).get("data_as_of") or rec.get("updated_at") or ""
    try:
        d = datetime.fromisoformat(src[:19] if "T" in src else src)
    except ValueError:
        return False
    return (datetime.now() - d).days > stale_days


def _diff(prev: dict | None, cur: dict) -> list[dict]:
    """אילו תוצאות מפתח השתנו לעומת הרשומה הקודמת (ריק = חישוב ראשון או ללא שינוי)."""
    if not prev or not prev.get("result") or not cur.get("result"):
        return []
    out = []
    for label, (a, b) in _KEYS.items():
        p, c = prev["result"][a][b], cur["result"][a][b]
        if isinstance(p, float) or isinstance(c, float):
            if abs(float(p) - float(c)) > 0.5:
                out.append({"what": label, "from": p, "to": c})
        elif p != c:
            out.append({"what": label, "from": p, "to": c})
    return out


# החלטה 14: סטטוס טיפול ידני (לא משפיע על החישוב)
HANDLING_STATUSES = ["טרם טופל", "בשיחה", "הוחלט: חלוקה", "הוחלט: שכר", "הוחלט: לא לפעול", "טופל"]

DEFAULT_SETTINGS = {
    "default_tax_year": 2026,
    "firm_name": "",                        # לחתימת המכתב ללקוח
    "accountant_name": "",
    "stale_days": 60,                       # החלטה 15: נתון מיושן אחרי כמה ימים
    "flags": {                              # הדגלים של הנקודות הפתוחות – ניתנים לשינוי בלי קוד אחרי הפגישה
        "deduct_transition_from_50pct_base": False,
        "enable_20pct_current_year_rule": True,
        "deduction_base_excludes_related_payments": False,
        "profitability_warning_threshold": 0.20,
    },
}


class Settings:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        out = json.loads(json.dumps(DEFAULT_SETTINGS))
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                out.update({k: v for k, v in saved.items() if k != "flags"})
                out["flags"].update(saved.get("flags", {}))
            except Exception:  # noqa: BLE001
                pass
        return out

    def save(self, data: dict) -> dict:
        cur = self.load()
        cur.update({k: v for k, v in data.items() if k != "flags"})
        cur["flags"].update(data.get("flags", {}))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        return cur


class ClientStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else app_dir() / "data" / "clients"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(self.root / "_settings.json")   # בתוך תיקיית הנתונים; קבצי _ אינם לקוחות

    # ---- helpers
    def _path(self, cid: str) -> Path:
        if not re.fullmatch(r"[\w\-]+", cid) or cid.startswith("_"):
            raise ValueError("מזהה לקוח לא תקין")
        return self.root / f"{cid}.json"

    @staticmethod
    def _new_id(inp: dict[str, Any]) -> str:
        cid = str(inp.get("structure", {}).get("company_id") or "").strip()
        return cid if re.fullmatch(r"\d{5,9}", cid) else uuid.uuid4().hex[:10]

    # ---- read
    def list(self) -> list[dict[str, Any]]:
        out = []
        stale_days = self.settings.load()["stale_days"]
        for f in sorted(self.root.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                rec["stale"] = _is_stale(rec, stale_days)
                out.append(rec)
            except Exception as e:  # noqa: BLE001 – קובץ פגום לא מפיל את הרשימה
                out.append({"id": f.stem, "error": str(e)})
        return out

    def get(self, cid: str) -> dict[str, Any] | None:
        p = self._path(cid)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    # ---- write
    def save(self, inp: dict[str, Any], cid: str | None = None) -> dict[str, Any]:
        inp = dict(inp)
        inp["flags"] = {**(inp.get("flags") or {}), **self.settings.load()["flags"]}   # הדגלים מההגדרות גוברים
        inp["data_as_of"] = _normalize_date(inp.get("data_as_of") or "")
        ci = ClientInput.from_dict(inp)          # מאמת שדות
        is_new = cid is None
        cid = cid or self._new_id(inp)
        prev = self.get(cid)
        if is_new and prev:                      # לקוח חדש עם ח.פ. של לקוח קיים – לא דורסים בשקט
            raise ValueError(f"לקוח עם ח.פ. {cid} כבר קיים ({(prev.get('input') or {}).get('structure', {}).get('name', '')}) – לערוך אותו במקום")
        rec = {
            "id": cid,
            "input": ci.to_dict(),
            "result": None,
            "error": None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "created_at": (prev or {}).get("created_at") or datetime.now().isoformat(timespec="seconds"),
            "logic_version": LOGIC_VERSION,
            "handling": (prev or {}).get("handling") or {"status": HANDLING_STATUSES[0], "note": "", "at": None},
        }
        try:
            rec["result"] = compute(ci).to_dict()
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)
        rec["changes"] = _diff(prev, rec)                    # החלטה 6 – מה זז לעומת החישוב הקודם
        rec["previous_logic_version"] = (prev or {}).get("logic_version")
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def set_handling(self, cid: str, status: str, note: str = "") -> dict[str, Any] | None:
        rec = self.get(cid)
        if not rec:
            return None
        if status not in HANDLING_STATUSES:
            raise ValueError("סטטוס לא מוכר")
        rec["handling"] = {"status": status, "note": note, "at": datetime.now().isoformat(timespec="seconds")}
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def delete(self, cid: str) -> bool:
        p = self._path(cid)
        if p.exists():
            p.unlink()
            return True
        return False

    def recompute_all(self, only_outdated: bool = False) -> int:
        """מחשב מחדש את כל הלקוחות. only_outdated=True – רק מי שחושב בגרסת לוגיקה ישנה (אחרי update.bat)."""
        n = 0
        for rec in self.list():
            if "input" in rec and (not only_outdated or rec.get("logic_version") != LOGIC_VERSION):
                self.save(rec["input"], rec["id"])
                n += 1
        return n

    def export_document(self, cid: str, kind: str = "accountant", fmt: str = "pdf") -> Path | None:
        from .documents import export
        rec = self.get(cid)
        if not rec or not rec.get("result"):
            return None
        st = self.settings.load()
        try:
            return export(compute(ClientInput.from_dict(rec["input"])), kind, fmt, self.root.parent / "reports",
                          handling=rec.get("handling"), firm_name=st.get("firm_name", ""), accountant_name=st.get("accountant_name", ""))
        except PermissionError as e:
            raise RuntimeError("הקובץ הקודם פתוח (בוורד/בדפדפן) – לסגור אותו ולייצא שוב") from e

    def export_report(self, cid: str) -> Path | None:
        rec = self.get(cid)
        if not rec or not rec.get("result"):
            return None
        out = self.root.parent / "reports"
        out.mkdir(exist_ok=True)
        p = out / f"{rec['result']['name'] or cid}.md"
        p.write_text(render_markdown(compute(ClientInput.from_dict(rec["input"]))), encoding="utf-8")
        return p
