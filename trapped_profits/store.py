"""אחסון לקוחות: קובץ JSON לכל לקוח בתיקיית data/clients ליד התוכנה.

כל קובץ: {"id", "input", "result", "updated_at", "logic_version"}.
שמירה = חישוב מיידי. אברהם 14.10 (16, 19): כל חישוב, שינוי סטטוס והערה נרשמים ב-"history" של הלקוח
(מה בדקנו, מה יצא, מה המלצנו) – לתצוגה לפי רבעונים ושנים.
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


def _summary(rec: dict) -> str:
    r = rec.get("result")
    if not r:
        return "החישוב נכשל: " + str(rec.get("error") or "")
    return (f"{r['dashboard']['status_overall']} · תוספת מס {r['calc81']['surtax']:,.0f} ₪ · "
            f"שכר לתיקון {r['s62a']['attributed_income']:,.0f} ₪")


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


# אברהם 14.10 (3): מצב לכל שדה – מהקובץ (לאישור) / אושר / ידני; ושדות שרק אדם יודע
FIELD_STATES = ("file", "approved", "manual", "carried", "estimate")
# carried = הועבר ממעבר שנה (ערך מהשנה הקודמת שאינו בקבצים); estimate = אומדן של המערכת (לבדיקת אברהם)
FIELD_SKIP = ("flags", "data_as_of")                 # לא נרשמת להם היסטוריית ערכים


def _flatten(d: dict, prefix: str = "") -> dict:
    """{"a": {"b": 1}} → {"a.b": 1}; רשימות (לקוחות גדולים) נשארות ערך אחד."""
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _record_changes(prev_inp: dict | None, new_inp: dict, meta: dict, by: str) -> dict:
    """אברהם (סבב 2, 9+13): כל ערך שנשמר הוא רשומה – ערך קודם, מקור, מי ומתי. שינוי בלי מצב מפורש = ידני."""
    now = datetime.now().isoformat(timespec="seconds")
    old, new = _flatten(prev_inp or {}), _flatten(new_inp)
    for path, val in new.items():
        if path.split(".")[0] in FIELD_SKIP:
            continue
        m = meta.get(path)
        changed = prev_inp is not None and path in old and old[path] != val
        if m is not None and m.get("_new") and not m.get("by"):
            m["by"] = by                                    # רשומה חדשה מהשמירה הזו
        if not changed:
            continue
        if m is None:
            m = meta[path] = {"state": "manual", "source": "טופס", "at": now, "by": by}
        elif not m.get("_new"):                             # הערך השתנה בלי מצב חדש – עריכה ידנית
            m.update(state="manual", source="טופס", at=now, by=by)
        hist = m.setdefault("prev", [])
        hist.append({"value": old[path], "state": m.get("_old_state"), "at": m.get("_old_at"), "source": m.get("_old_source")})
        del hist[:-20]
    for m in meta.values():
        for k in ("_old_state", "_old_at", "_old_source", "_new"):
            m.pop(k, None)
    return meta
HUMAN_ONLY_FIELDS = {
    "structure.company_id": "מספר ח.פ.",
    "structure.controlling_owner_name": "שם בעל השליטה",
    "structure.controlling_owners_count": "מספר בעלי השליטה",
    "structure.group_companies_count": "חברות מעטים בשליטת בעל השליטה",
    "structure.owner_controls_another_company": "בעל שליטה בחברה אחרת",
    "shields.total_assets_cost": "עלות כלל נכסי החברה",
    "distributions.dividends_taxed_current_year": "דיבידנד ששולם עליו מס השנה",
    "distributions.determining_period_paid_and_taxed": "המס על דיבידנד 2025 שולם עד 31.12.2025",
    "s62a.owner_salary_current_year": "שכר בעלים ששולם השנה",
}


def _missing_human(meta: dict, inp: dict | None = None) -> list[str]:
    """שדות שרק אדם יודע ועדיין לא נגעו בהם (אין מצב ידני/מאושר). בתרחיש ב׳ גם דיבידנד השנה הקודמת."""
    fields = dict(HUMAN_ONLY_FIELDS)
    st = (inp or {}).get("structure") or {}
    if st.get("last_closed_report_year") and st.get("tax_year") and st["last_closed_report_year"] < st["tax_year"] - 1:
        fields["distributions.dividends_prev_year"] = "דיבידנד שחולק בשנה הקודמת (לגלגול)"
    return [label for path, label in fields.items()
            if (meta.get(path) or {}).get("state") not in ("manual", "approved")]


def _merge_meta(prev: dict | None, new: dict | None) -> dict:
    out = {k: dict(v) for k, v in (prev or {}).items()}
    now = datetime.now().isoformat(timespec="seconds")
    for k, v in (new or {}).items():
        if not isinstance(v, dict) or v.get("state") not in FIELD_STATES:
            continue
        old = out.get(k) or {}
        if old and old.get("state") == v["state"] and old.get("source") == str(v.get("source") or "") and not v.get("force"):
            continue                                         # הטופס שולח גם את המצב הקיים – לא רשומה חדשה
        out[k] = {"state": v["state"], "source": str(v.get("source") or ""), "at": now, "by": v.get("by"),
                  "prev": old.get("prev") or [], "_new": True,
                  "_old_state": old.get("state"), "_old_at": old.get("at"), "_old_source": old.get("source")}
    for k, m in out.items():                                 # שדות שלא נגעו בהם – שומרים מי היה לפני
        if "_old_state" not in m:
            m.update(_old_state=m.get("state"), _old_at=m.get("at"), _old_source=m.get("source"))
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
    def save(self, inp: dict[str, Any], cid: str | None = None, field_meta: dict | None = None) -> dict[str, Any]:
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
            "letter_note": (prev or {}).get("letter_note", ""),      # אברהם 14.10 (18) – טקסט חופשי למכתב
            "history": (prev or {}).get("history") or [],
            "field_meta": _merge_meta((prev or {}).get("field_meta"), field_meta),
            "years": (prev or {}).get("years") or {},            # תמונות של שנים שנסגרו (מעבר שנה)
        }
        rec["field_meta"] = _record_changes((prev or {}).get("input"), rec["input"], rec["field_meta"], self._by())
        rec["missing_human"] = _missing_human(rec["field_meta"], rec["input"])
        rec["pending_file_fields"] = [k for k, v in rec["field_meta"].items() if v.get("state") == "file"]
        try:
            rec["result"] = compute(ci).to_dict()
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)
        rec["changes"] = _diff(prev, rec)                    # החלטה 6 – מה זז לעומת החישוב הקודם
        rec["previous_logic_version"] = (prev or {}).get("logic_version")
        self._log(rec, "חישוב", _summary(rec), changes=rec["changes"])
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def _by(self) -> str:
        return (self.settings.load().get("accountant_name") or "").strip() or "המשרד"

    def _write(self, cid: str, rec: dict) -> dict:
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    @staticmethod
    def _get_path(inp: dict, path: str):
        cur = inp
        for pth in path.split("."):
            if not isinstance(cur, dict) or pth not in cur:
                return None
            cur = cur[pth]
        return cur

    @staticmethod
    def _set_path(inp: dict, path: str, value: Any) -> None:
        parts = path.split(".")
        target = inp
        for pth in parts[:-1]:
            target = target.setdefault(pth, {})
        target[parts[-1]] = value

    def revert_field(self, cid: str, path: str) -> dict[str, Any]:
        """אברהם (סבב 2, 16): ביטול – חזרה לערך הקודם של השדה (מהקובץ / ידני קודם)."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        m = (rec.get("field_meta") or {}).get(path) or {}
        if not m.get("prev"):
            raise ValueError("אין ערך קודם לשדה הזה")
        last = m["prev"].pop()
        self._set_path(rec["input"], path, last["value"])
        state = last.get("state") if last.get("state") in FIELD_STATES else "manual"
        src = f"בוטל {m.get('at', '')[:10]} – חזרה ל: {last.get('source') or 'ערך קודם'}"
        meta = {path: {"state": state, "source": src, "force": True}}
        new = self.save(rec["input"], cid, field_meta=meta)
        new["field_meta"][path]["prev"] = m["prev"]          # הביטול עצמו לא נרשם כשלב נוסף
        self._log(new, "ביטול", f"{path}: חזרה ל-{last['value']}")
        return self._write(cid, new)

    def revert_today(self, cid: str) -> dict[str, Any]:
        """אברהם (סבב 2, 16): ביטול כל השינויים הידניים מהיום."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        today = datetime.now().date().isoformat()
        paths = [k for k, v in (rec.get("field_meta") or {}).items()
                 if v.get("prev") and str(v.get("at", "")).startswith(today) and v.get("state") in ("manual", "estimate")]
        for p in paths:
            rec = self.revert_field(cid, p)
        if paths:
            self._log(rec, "ביטול", f"בוטלו {len(paths)} שינויים מהיום")
            self._write(cid, rec)
        return rec

    @staticmethod
    def _log(rec: dict, kind: str, text: str, **extra: Any) -> None:
        """רשומת היסטוריה אחת: מתי, מה, ומה היה המצב באותו רגע."""
        r = rec.get("result") or {}
        entry = {"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, "text": text,
                 "tax_year": (rec.get("input") or {}).get("structure", {}).get("tax_year"),
                 "snapshot": {
                     "color": r.get("dashboard", {}).get("color_overall"),
                     "status": r.get("dashboard", {}).get("status_overall"),
                     "surtax": r.get("calc81", {}).get("surtax"),
                     "gap": r.get("simulator", {}).get("gap_to_close"),
                     "attributed": r.get("s62a", {}).get("attributed_income"),
                     "retained": (rec.get("input") or {}).get("retained", {}).get("balance_sheet_retained_earnings"),
                     "recommendation": r.get("simulator", {}).get("recommendation_text"),
                 } if r else None, **extra}
        hist = rec.setdefault("history", [])
        hist.append(entry)
        del hist[:-300]

    def set_letter_note(self, cid: str, note: str) -> dict[str, Any] | None:
        rec = self.get(cid)
        if not rec:
            return None
        rec["letter_note"] = note
        self._log(rec, "הערה למכתב", note)
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def approve_fields(self, cid: str, paths: list[str] | None = None) -> dict[str, Any]:
        """אישור שדות שמולאו מקובץ – כולם (None) או רשימה."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        meta = rec.get("field_meta") or {}
        now = datetime.now().isoformat(timespec="seconds")
        n = 0
        for k, v in meta.items():
            if v.get("state") == "file" and (paths is None or k in paths):
                v.update(state="approved", at=now)
                n += 1
        rec["field_meta"] = meta
        rec["missing_human"] = _missing_human(meta, rec.get("input"))
        rec["pending_file_fields"] = [k for k, v in meta.items() if v.get("state") == "file"]
        self._log(rec, "אישור", f"אושרו {n} שדות מהקובץ")
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def apply_import(self, cid: str, fields: dict, sources: dict | None, label: str) -> dict[str, Any]:
        """אברהם 14.10 (2): עדכון רבעוני מקובץ בכרטיס לקוח קיים – דורס רק את השדות שבקובץ, מחשב, ורושם בהיסטוריה."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        meta = {}
        now = datetime.now().isoformat(timespec="seconds")
        for path, value in (fields or {}).items():
            parts = path.split(".")
            target = inp
            for pth in parts[:-1]:
                target = target.setdefault(pth, {})
            if parts[-1] not in target and path not in ("data_as_of", "data_through_month"):
                continue
            target[parts[-1]] = value
            meta[path] = {"state": "file", "source": (sources or {}).get(path, label), "at": now}
        new = self.save(inp, cid, field_meta=meta)
        self._log(new, "עדכון מקובץ", f"{label} – {len(meta)} שדות")
        self._path(cid).write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
        return new

    def update_field(self, cid: str, path: str, value: Any) -> dict[str, Any]:
        """אברהם 14.10 (3, 15): עריכת שדה בודד מהתור/מהכרטיס – שומר ומחשב מחדש."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        parts = path.split(".")
        target = inp
        for pth in parts[:-1]:
            target = target.setdefault(pth, {})
        if parts[-1] not in target and path not in ("data_as_of", "data_through_month"):
            raise ValueError(f"שדה לא מוכר: {path}")
        target[parts[-1]] = value
        return self.save(inp, cid, field_meta={path: {"state": "manual", "source": "עריכה ישירה"}})

    def set_handling(self, cid: str, status: str, note: str = "") -> dict[str, Any] | None:
        rec = self.get(cid)
        if not rec:
            return None
        if status not in HANDLING_STATUSES:
            raise ValueError("סטטוס לא מוכר")
        rec["handling"] = {"status": status, "note": note, "at": datetime.now().isoformat(timespec="seconds")}
        self._log(rec, "טיפול", f"{status}" + (f" – {note}" if note else ""))
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    @staticmethod
    def safe_name(name: str) -> str:
        return "".join(ch for ch in str(name) if ch not in '\\/:*?"<>|').strip() or "לקוח"

    def delete(self, cid: str) -> bool:
        """מחיקה = ארכוב: הרשומה, עותקי הקבצים שהועלו והדוחות עוברים ל-data/_deleted/<שם> – <תאריך>/. שום דבר לא מושמד."""
        import shutil
        p = self._path(cid)
        if not p.exists():
            return False
        rec = self.get(cid) or {}
        name = self.safe_name((rec.get("input") or {}).get("structure", {}).get("name") or cid)
        data = self.root.parent
        dst = data / "_deleted" / f"{name} – {datetime.now().strftime('%Y-%m-%d %H%M')}"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dst / p.name))
        files = data / "files" / name
        if files.exists():
            shutil.move(str(files), str(dst / "files"))
        reports = data / "reports"
        if reports.exists():
            for f in reports.glob(f"{name} – *"):
                (dst / "reports").mkdir(exist_ok=True)
                shutil.move(str(f), str(dst / "reports" / f.name))
        return True

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
                          handling=rec.get("handling"), firm_name=st.get("firm_name", ""), accountant_name=st.get("accountant_name", ""),
                          letter_note=rec.get("letter_note", ""), history=rec.get("history") or [],
                          pending_fields=rec.get("pending_file_fields") or [], missing_human=rec.get("missing_human") or [])
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
