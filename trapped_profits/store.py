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


def data_root() -> Path:
    """תיקיית הנתונים: ברירת מחדל <תוכנה>/data; אפשר להפנות לתיקייה אחרת דרך הקובץ data_dir.txt (הגדרות → תיקיית הנתונים)."""
    ptr = app_dir() / "data_dir.txt"
    if ptr.exists():
        p = Path(ptr.read_text(encoding="utf-8").strip())
        if p.is_absolute():
            return p
    return app_dir() / "data"


def set_data_root(path: Path) -> None:
    (app_dir() / "data_dir.txt").write_text(str(path), encoding="utf-8")


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
FIELD_SKIP = ("flags", "data_as_of", "period_breakdown", "period_breakdown_prev_year", "months_without_revenue", "period_breakdown_months", "adjustments", "tb_rows", "tb_rows_prev_year", "tb_approved", "tb_cogs", "gp_checked", "tb_kind", "ai_annual", "ai_tb")
TOP_LEVEL_FIELDS = ("data_as_of", "data_through_month", "period_breakdown", "period_breakdown_prev_year", "months_without_revenue", "period_breakdown_months", "adjustments", "tb_rows", "tb_rows_prev_year", "tb_approved", "tb_cogs", "gp_checked", "tb_kind", "ai_annual", "ai_tb")                 # לא נרשמת להם היסטוריית ערכים


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


def _record_changes(prev_inp: dict | None, new_inp: dict, meta: dict, by: str, reset: tuple = ()) -> dict:
    """אברהם (סבב 2, 9+13): כל ערך שנשמר הוא רשומה – ערך קודם, מקור, מי ומתי. שינוי בלי מצב מפורש = ידני."""
    now = datetime.now().isoformat(timespec="seconds")
    old, new = _flatten(prev_inp or {}), _flatten(new_inp)
    for path, val in new.items():
        if path.split(".")[0] in FIELD_SKIP:
            continue
        if any(path == r or path.startswith(r + ".") for r in reset):   # אופס במעבר שנה – לא עריכה ידנית
            meta.pop(path, None)
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


def _model_has(path: str) -> bool:
    """שדה שקיים במודל גם אם עוד לא נשמר ללקוח (לקוח ישן / שדה חדש) – מותר לערוך אותו מהכרטיס."""
    try:
        d = ClientInput().to_dict()
    except Exception:  # noqa: BLE001
        return False
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return False
        d = d[part]
    return True


def _prune_ai(rec: dict) -> None:
    """21.10: סתירה בין הקוראים נסגרת כשאברהם הזין/אישר את השדה אחרי שהסתירה נוצרה."""
    ai = (rec.get("input") or {}).get("ai_annual") or {}
    conf = ai.get("conflicts") or {}
    meta = rec.get("field_meta") or {}
    for path in list(conf):
        m = meta.get(path) or {}
        if m.get("state") in ("manual", "approved") and str(m.get("at") or "") > str(conf[path].get("at") or ai.get("at") or ""):
            conf.pop(path, None)


def _missing_human(meta: dict, inp: dict | None = None) -> list[str]:
    """שדות שרק אדם יודע ועדיין לא נגעו בהם (אין מצב ידני/מאושר). בתרחיש ב׳ גם דיבידנד השנה הקודמת.
    21.10: וסתירות בין הקורא שלנו לבודק השני – עד שאברהם בוחר."""
    conf = (((inp or {}).get("ai_annual") or {}).get("conflicts") or {})
    # 22.10: סתירת OCR/AI כבר בחישוב (ערך ה-AI) – לא "חסר"; קריאה מחדש / הוזן ידנית – עדיין ממתינות לבחירה
    extra = [f"הקורא החדש מצא ערך אחר: {c.get('label') or p}" if c.get("ours_name") != "הוזן ידנית" else f"הקובץ החדש שונה מההזנה הידנית: {c.get('label') or p}"
             for p, c in conf.items() if c.get("reread")]
    return extra + _missing_human_base(meta, inp)


def _missing_human_base(meta: dict, inp: dict | None = None) -> list[str]:
    fields = dict(HUMAN_ONLY_FIELDS)
    st = (inp or {}).get("structure") or {}
    if st.get("last_closed_report_year") and st.get("tax_year") and st["last_closed_report_year"] < st["tax_year"] - 1:
        fields["distributions.dividends_prev_year"] = "דיבידנד שחולק בשנה הקודמת (לגלגול)"
    if st.get("last_closed_report_year") and st.get("tax_year") and st["last_closed_report_year"] < st["tax_year"] - 2:
        fields["distributions.dividends_prev2_year"] = "דיבידנד שחולק בשנה שלפני הקודמת (לגלגול)"
    return [label for path, label in fields.items()
            if (meta.get(path) or {}).get("state") not in ("manual", "approved")]


def _merge_sources(prev: list | None, new: list | None) -> list:
    """רשימת הקבצים שהועלו: קובץ חדש לאותו חריץ מסמן את הקודם כ"הוחלף" (נשאר לתיעוד, עם סימון הבדיקה שלו)."""
    out = [dict(x) for x in (prev or [])]
    for src in new or []:
        if not isinstance(src, dict) or not src.get("slot"):
            continue
        for old in out:
            if old.get("slot") == src["slot"] and not old.get("superseded"):
                old["superseded"] = True
        out.append({"slot": src["slot"], "title": src.get("title", ""), "year": src.get("year"), "file": src.get("file", ""),
                    "path": src.get("path", ""), "at": src.get("at") or datetime.now().isoformat(timespec="seconds"),
                    "fields": int(src.get("fields") or 0), "through_month": src.get("through_month"), "reviewed": None})
    return out[-40:]


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
    "firm_name": "מדהלה שלמה ושות'",        # לחתימת המכתב ללקוח (22.10: המוצר של המשרד – ברירת מחדל)
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
                out.update({k: v for k, v in saved.items() if k != "flags" and not (k == "firm_name" and not str(v or "").strip())})
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
        self.root = Path(root) if root else data_root() / "clients"
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
    def save(self, inp: dict[str, Any], cid: str | None = None, field_meta: dict | None = None, reset_paths: tuple = (), sources: list | None = None) -> dict[str, Any]:
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
            "sources": _merge_sources((prev or {}).get("sources"), sources),   # סבב 3: הקבצים שהלקוח מבוסס עליהם
            "report_parser_version": (prev or {}).get("report_parser_version"),
            "review": (prev or {}).get("review"),
        }
        # 22.10: מבקר – שינוי בנתונים אחרי הבדיקה → הממצאים "ייתכן שלא עדכניים"
        if rec["review"] and prev and rec["review"].get("status") == "done" and (prev.get("input") or {}) != rec["input"]:
            rec["review"] = {**rec["review"], "stale": True}
        if any(isinstance(x, dict) and x.get("slot") == "annual_report" for x in (sources or [])):
            from .annual_report import PARSER_VERSION
            rec["report_parser_version"] = PARSER_VERSION
        rec["field_meta"] = _record_changes((prev or {}).get("input"), rec["input"], rec["field_meta"], self._by(), reset_paths)
        _prune_ai(rec)
        rec["missing_human"] = _missing_human(rec["field_meta"], rec["input"])
        rec["pending_file_fields"] = [k for k, v in rec["field_meta"].items() if v.get("state") == "file" and k.split(".")[0] not in FIELD_SKIP]
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
        if last.get("state") in FIELD_STATES:
            src = f"בוטל {m.get('at', '')[:10]} – חזרה ל: {last.get('source') or 'ערך קודם'}"
            meta = {path: {"state": last["state"], "source": src, "force": True}}
        else:                                                # לא היה מצב קודם (שדה שמעולם לא הוזן) – חוזר ל"חסר"
            meta = None
            rec["field_meta"].pop(path, None)
            self._write(cid, rec)
        new = self.save(rec["input"], cid, field_meta=meta, reset_paths=() if meta else (path,))
        if path in new["field_meta"]:
            new["field_meta"][path]["prev"] = m["prev"]      # הביטול עצמו לא נרשם כשלב נוסף
        self._log(new, "ביטול", f"{path}: חזרה ל-{last['value']}")
        return self._write(cid, new)

    def revert_today(self, cid: str) -> dict[str, Any]:
        """אברהם (סבב 2, 16): ביטול כל השינויים הידניים מהיום."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        today = datetime.now().date().isoformat()
        paths = [k for k, v in (rec.get("field_meta") or {}).items()
                 if v.get("prev") and str(v.get("at", "")).startswith(today) and v.get("state") == "manual"]
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
        rec["pending_file_fields"] = [k for k, v in meta.items() if v.get("state") == "file" and k.split(".")[0] not in FIELD_SKIP]
        self._log(rec, "אישור", f"אושרו {n} שדות מהקובץ")
        self._path(cid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def apply_import(self, cid: str, fields: dict, sources: dict | None, label: str, source: dict | None = None, keep_manual: bool = True) -> dict[str, Any]:
        """אברהם 14.10 (2): עדכון רבעוני מקובץ בכרטיס לקוח קיים – דורס רק את השדות שבקובץ, מחשב, ורושם בהיסטוריה."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        meta = {}
        now = datetime.now().isoformat(timespec="seconds")
        superseded: list[str] = []
        if "tb_rows" in (fields or {}):
            # סבב 4: קובץ חדש ממלא חודשים שהיו אומדן – תיקון ידני על חודש כזה מוחלף על ידי הקובץ; תיקון על חודש שהיה בקובץ נשאר
            old_m = int(inp.get("data_through_month") or 0)
            new_m = int((fields or {}).get("data_through_month") or 12)
            keep = []
            for a in inp.get("adjustments") or []:
                mth = int(a.get("month") or 0)
                if str(a.get("key", "")).startswith("tb:") and mth and old_m < mth <= new_m:
                    superseded.append(f"{a.get('key')} · חודש {mth} ({float(a.get('amount') or 0):,.0f} ₪)")
                    continue
                keep.append(a)
            inp["adjustments"] = keep
        if (source or {}).get("slot") == "annual_report" and "ai_annual" not in (fields or {}):
            inp["ai_annual"] = {}                                         # דוח חדש – סתירות של הדוח הקודם כבר לא רלוונטיות
        if "retained.balance_sheet_retained_earnings" in (fields or {}):
            inp.setdefault("retained", {})["retained_as_of_year"] = None      # דוח סגור חדש – העודפים שוב "מהדוח", לא אומדן מגולגל
        old_meta = rec.get("field_meta") or {}
        kept: list[str] = []
        if "ai_annual" in (fields or {}):
            inp["ai_annual"] = json.loads(json.dumps(fields["ai_annual"]))     # קודם – כדי שסתירות "הוזן ידנית" יתווספו אליו
        for path, value in (fields or {}).items():
            if path == "ai_annual":
                continue
            parts = path.split(".")
            target = inp
            for pth in parts[:-1]:
                target = target.setdefault(pth, {})
            if parts[-1] not in target and path not in TOP_LEVEL_FIELDS:
                continue
            # 22.10: ערך שהוקלד ידנית לא נדרס מקובץ – נפתחת סתירה (הוזן ידנית / הקובץ) לבחירה
            if keep_manual and (old_meta.get(path) or {}).get("state") == "manual" and path.split(".")[0] not in FIELD_SKIP \
                    and not isinstance(value, (list, dict)) and target.get(parts[-1]) != value:
                from .ai_check import LABELS
                conf = inp.setdefault("ai_annual", {}).setdefault("conflicts", {})
                conf[path] = {"label": LABELS.get(path, path), "reread": True, "at": now,
                              "ours": target.get(parts[-1]), "ours_name": "הוזן ידנית", "ours_src": (old_meta.get(path) or {}).get("source", ""), "ours_also": {},
                              "model": value, "model_name": "הקובץ החדש", "model_src": (sources or {}).get(path, label), "model_also": {}}
                kept.append(path)
                continue
            target[parts[-1]] = value
            meta[path] = {"state": "file", "source": (sources or {}).get(path, label), "at": now}
        new = self.save(inp, cid, field_meta=meta, sources=[source] if source else None)
        self._log(new, "עדכון מקובץ", f"{label} – {len(meta)} שדות" + (f"; {len(kept)} ערכים שהוזנו ידנית לא נדרסו – לבחירה" if kept else "") + (f"; הוחלפו על ידי הקובץ {len(superseded)} תיקונים ידניים על חודשים שהיו אומדן: " + "; ".join(superseded) if superseded else ""))
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
        if parts[-1] not in target and path not in TOP_LEVEL_FIELDS and not _model_has(path):
            raise ValueError(f"שדה לא מוכר: {path}")
        target[parts[-1]] = value
        ((inp.get("ai_annual") or {}).get("conflicts") or {}).pop(path, None)     # 21.10: הזנה ידנית סוגרת סתירה בין הקוראים
        return self.save(inp, cid, field_meta={path: {"state": "manual", "source": "עריכה ישירה"}})

    # ---- אברהם (סבב 2, 9+13, 10): מעבר שנה
    def rollover_year(self, cid: str) -> dict[str, Any]:
        """סגירת שנת המס הנוכחית ופתיחת הבאה: מה שהוזן השנה (דיבידנד, הוצאות, מחזור, כרטסת) הופך ל"שנה קודמת"
        ונשמר גם אם אינו בשום קובץ; העודפים מגולגלים כאומדן עד שיגיע דוח סגור; תמונת השנה נשמרת ב-years.
        מחזיר את הרשומה החדשה עם checklist – מה הועבר ומה צריך לבדוק."""
        from .engine import _rolled_retained
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = json.loads(json.dumps(rec["input"]))
        res = rec.get("result") or {}
        st = inp["structure"]
        ty = int(st["tax_year"])
        new_ty = ty + 1
        by = self._by()
        old_meta = rec.get("field_meta") or {}
        factor = 1.0
        m = inp.get("data_through_month")
        if m and 1 <= int(m) <= 12:
            factor = 12.0 / int(m)
        ann = lambda v: round(float(v or 0) * factor)  # noqa: E731
        src_of = lambda path: (old_meta.get(path) or {}).get("source") or "הוזן ידנית"  # noqa: E731
        carried: dict[str, dict] = {}
        checklist: list[str] = []
        tag = f"מעבר שנה {ty}→{new_ty}"

        def carry(dst: str, value, src_path: str, label: str) -> None:
            self._set_path(inp, dst, value)
            carried[dst] = {"state": "carried", "source": f"{tag}: {label} ({src_of(src_path)})", "force": True}

        # תמונת השנה שנסגרה
        rec.setdefault("years", {})[str(ty)] = {
            "closed_at": datetime.now().isoformat(timespec="seconds"), "by": by,
            "input": rec["input"], "field_meta": old_meta, "summary": _summary(rec),
            "snapshot": (rec.get("history") or [{}])[-1].get("snapshot"),
        }

        # 1. עודפים: אומדן מגולגל לתום השנה שנסגרה (עד שיגיע דוח סגור)
        ci = ClientInput.from_dict(rec["input"])
        rolled = _rolled_retained(ci)
        d = inp["distributions"]
        profit_est = d.get("current_year_profit_estimate")
        if profit_est is None:
            profit_est = inp["s62a"].get("taxable_income_personal_effort") or 0
        profit_est = ann(profit_est)
        carry("retained.balance_sheet_retained_earnings", rolled, "retained.balance_sheet_retained_earnings",
              f"עודפים לתום {ty - 1}" + (f" לפי גלגול מדוח {st.get('last_closed_report_year')}" if ci.structure.is_scenario_b else " מהדוח הסגור"))
        carried["retained.balance_sheet_retained_earnings"]["state"] = "estimate" if ci.structure.is_scenario_b else "carried"
        # העודפים עכשיו לתום ty−1 (גם אם הדוח הסגור ישן יותר) – הגלגול הבא רק שנה אחת; שלב השנתיים (תרחיש ג׳) כבר בפנים
        self._set_path(inp, "retained.retained_as_of_year", ty - 1)
        self._set_path(inp, "retained.prev2_year_profit_for_rollover", None)
        self._set_path(inp, "distributions.dividends_prev2_year", 0.0)
        carry("retained.prev_year_profit_for_rollover", profit_est, "distributions.current_year_profit_estimate", f"רווח {ty} (אומדן שנתי) לגלגול")
        checklist.append(f"עודפים: הבסיס לתום {ty} הוא אומדן (עודפי הדוח הסגור + רווח {ty} אחרי מס − דיבידנד {ty}). כשייסגר דוח {ty} – להעלות אותו והאומדן יוחלף.")

        # 2. דיבידנדים וריכוזיות
        div = float(d.get("dividends_taxed_current_year") or 0)
        carry("distributions.dividends_prev_year", div, "distributions.dividends_taxed_current_year", f"דיבידנד {ty}")
        self._set_path(inp, "distributions.dividends_taxed_current_year", 0.0)
        checklist.append(f"דיבידנד {ty}: {div:,.0f} ₪ הועבר ל\"דיבידנד השנה הקודמת\" ומופחת מהעודפים. דיבידנד {new_ty} – להזין כשיחולק.")
        excess = ((res.get("calc81") or {}).get("excess_profits"))
        if excess is not None:
            carry("distributions.excess_profits_prev_year", float(excess), "retained.balance_sheet_retained_earnings", f"רווחים עודפים לתום {ty} מהחישוב")
        sh, s62 = inp["shields"], inp["s62a"]
        carry("shields.expenses_prev2_year", float(sh.get("expenses_prev_year") or 0), "shields.expenses_prev_year", f"הוצאות {ty - 1}")
        carry("shields.expenses_prev_year", ann(sh.get("expenses_current_year")), "shields.expenses_current_year", f"הוצאות {ty}" + (" (אומדן שנתי)" if factor != 1 else ""))
        self._set_path(inp, "shields.expenses_current_year", 0.0)
        checklist.append(f"מגן הוצאות: הממוצע עכשיו על {ty - 1}, {ty} ו-{new_ty}. הוצאות {new_ty} – ממאזן הבוחן הבא.")
        carry("s62a.prev_year_revenue_for_concentration", ann(s62.get("total_revenue")), "s62a.total_revenue", f"מחזור {ty}")
        carry("s62a.top_customers_prev_year", s62.get("top_customers") or [], "s62a.top_customers", f"כרטסת {ty}")
        for k, v in (("s62a.total_revenue", 0.0), ("s62a.taxable_income_personal_effort", 0.0), ("s62a.related_company_payments", 0.0),
                     ("s62a.top_customers", []), ("s62a.owner_salary_current_year", None), ("s62a.intercompany_dividend_received", 0.0),
                     ("distributions.losses_current_year", 0.0), ("distributions.current_year_profit_estimate", None),
                     ("shields.pay_62a_salary_by_year_end", False)):
            self._set_path(inp, k, v)
        checklist.append(f"ריכוזיות: נבדקת על {ty - 1}–{new_ty}; כרטסת {new_ty} חסרה עד ההעלאה הבאה.")
        inp["period_breakdown_prev_year"] = inp.get("period_breakdown") or {}
        inp["period_breakdown"] = {}
        inp["months_without_revenue"] = []
        inp["tb_rows_prev_year"] = inp.get("tb_rows") or []
        inp["tb_rows"] = []
        inp["tb_approved"] = {}
        inp["period_breakdown_months"] = {}
        inp["adjustments"] = [a for a in (inp.get("adjustments") or []) if not a.get("month")]   # תיקוני חודשים שייכים לשנה שנסגרה
        carry("s62a.top_customers_prev2_year", s62.get("top_customers_prev_year") or [], "s62a.top_customers_prev_year", f"כרטסת {ty - 1}")
        carry("s62a.prev2_year_revenue_for_concentration", float(s62.get("prev_year_revenue_for_concentration") or 0), "s62a.prev_year_revenue_for_concentration", f"מחזור {ty - 1}")
        for k in ("s62a.purchases_current_year",):
            self._set_path(inp, k, None)
        inp["data_through_month"] = None
        inp["data_as_of"] = ""
        st["tax_year"] = new_ty

        # 3. הגנת מעבר
        prot = (res.get("transition") or {}).get("protected_until_year") or 0
        if prot and prot < new_ty:
            checklist.append(f"הגנת המעבר פקעה (הייתה עד {prot}) – ב-{new_ty} הלקוח חשוף לפי המבחנים הרגילים.")
        elif prot:
            checklist.append(f"הגנת המעבר עדיין בתוקף עד {prot}.")
        checklist.append(f"להעלות ל-{new_ty}: מאזן בוחן לפי חודשים + כרטסת הכנסות (עדכון רבעוני); דוח שנתי {ty} כשייסגר.")

        # שדות התקופה שאופסו – מצבם נמחק (יוצגו כחסרים / ריקים), לא נרשמים כעריכה ידנית
        reset = ("s62a.total_revenue", "s62a.taxable_income_personal_effort", "s62a.related_company_payments", "s62a.top_customers",
                 "s62a.owner_salary_current_year", "s62a.intercompany_dividend_received", "distributions.dividends_taxed_current_year",
                 "distributions.losses_current_year", "distributions.current_year_profit_estimate", "shields.expenses_current_year",
                 "shields.pay_62a_salary_by_year_end", "data_through_month", "structure.tax_year", "s62a.purchases_current_year")
        self._write(cid, rec)
        new = self.save(inp, cid, field_meta=carried, reset_paths=reset)
        new["rollover_checklist"] = checklist
        self._log(new, "מעבר שנה", f"{tag}: " + " · ".join(checklist), checklist=checklist)
        return self._write(cid, new)

    # ---- סבב 3: תיקונים מעל הקבצים, מקורות, סימון "נבדק"
    def approve_tb(self, cid: str, undo: bool = False) -> dict[str, Any]:
        """אברהם 15.10: "אשר הכל" במאזן הבוחן – כל האומדנים, החורים והאומדנים השנתיים (פחת/מלאי) מאושרים;
        התיקונים הידניים נשארים כמו שהם; קובץ מאזן הבוחן מסומן "עברתי – נבדק". קובץ חדש (חודש אחר) – האישור פג מעצמו."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        now = datetime.now().isoformat(timespec="seconds")
        if undo:
            inp["tb_approved"] = {}
        else:
            inp["tb_approved"] = {"by": self._by(), "at": now, "through_month": int(inp.get("data_through_month") or 12)}
        new = self.save(inp, cid)
        if not undo:
            for s in new.get("sources") or []:
                if s.get("slot") == "trial_balance" and not s.get("superseded") and not s.get("reviewed"):
                    s["reviewed"] = {"by": self._by(), "at": now}
        n_manual = sum(1 for a in inp.get("adjustments") or [] if str(a.get("key", "")).startswith("tb:") and a.get("kind") == "manual")
        self._log(new, "נבדק", "בוטל אישור מאזן הבוחן" if undo else
                  f"מאזן בוחן אושר (עד חודש {inp['tb_approved']['through_month']}) – כל האומדנים מאושרים" + (f"; {n_manual} תיקונים ידניים נשמרו" if n_manual else ""))
        return self._write(cid, new)

    def resolve_ai(self, cid: str, path: str, choice: str) -> dict[str, Any]:
        """21.10: אברהם בוחר בין הקורא שלנו (ours) לבודק השני (model) בשדה מהדוח השנתי."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        conf = ((inp.get("ai_annual") or {}).get("conflicts") or {})
        c = conf.get(path)
        if not c or choice not in ("ours", "model"):
            raise ValueError("הסתירה כבר נסגרה")
        vals = {path: c[choice], **(c.get(choice + "_also") or {})}
        meta = {}
        now = datetime.now().isoformat(timespec="seconds")
        who = c.get(choice + "_name") or ("OCR" if choice == "ours" else "AI")
        for p, v in vals.items():
            parts = p.split(".")
            t = inp
            for x in parts[:-1]:
                t = t.setdefault(x, {})
            t[parts[-1]] = v
            meta[p] = {"state": "approved", "source": f"נבחר: {who} – " + (c.get(choice + "_src") or ""), "at": now}
        conf.pop(path, None)
        new = self.save(inp, cid, field_meta=meta)
        shown = f"{v:,.0f}" if isinstance((v := c[choice]), (int, float)) and not isinstance(v, bool) and abs(v) > 1 else str(v)
        self._log(new, "תיקון", f"{c.get('label') or path}: נבחר {who} ({shown})")
        return self._write(cid, new)

    # ---- 22.10: מבקר
    def review_start(self, cid: str) -> dict | None:
        rec = self.get(cid)
        if not rec:
            return None
        rv = dict(rec.get("review") or {})
        rv.update(status="running", started=datetime.now().isoformat(timespec="seconds"))
        rec["review"] = rv
        return self._write(cid, rec)

    def review_finish(self, cid: str, result: dict | None = None, error: str = "") -> dict | None:
        rec = self.get(cid)
        if not rec:
            return None
        old = rec.get("review") or {}
        now = datetime.now().isoformat(timespec="seconds")
        if error:
            rec["review"] = {**old, "status": "error", "msg": error, "at": now}
        else:
            dismissed = list(old.get("dismissed") or []) + [f for f in old.get("findings") or [] if f.get("state") in ("checked", "irrelevant")]
            seen, dd = set(), []
            for f in reversed(dismissed):
                k = (f.get("title"), f.get("field"))
                if k not in seen:
                    seen.add(k); dd.append(f)
            rec["review"] = {"status": "done", "at": now, "stale": False, "msg": "", "overall": (result or {}).get("overall", ""),
                             "findings": (result or {}).get("findings") or [], "dismissed": list(reversed(dd))[-30:]}
            n = len(rec["review"]["findings"])
            self._log(rec, "בדיקת היגיון", f"{n} ממצאים" if n else "לא נמצאו ממצאים")
        return self._write(cid, rec)

    def review_mark(self, cid: str, fid: str, state: str) -> dict:
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        if state not in ("open", "checked", "irrelevant"):
            raise ValueError("מצב לא מוכר")
        for f in (rec.get("review") or {}).get("findings") or []:
            if f.get("id") == fid:
                f["state"] = state
                f["by"], f["at"] = self._by(), datetime.now().isoformat(timespec="seconds")
                if state != "open":
                    self._log(rec, "בדיקת היגיון", f"{f.get('title') or f.get('finding', '')[:40]}: {'נבדק' if state == 'checked' else 'לא רלוונטי'}")
        return self._write(cid, rec)

    def resolve_ai_all(self, cid: str, choice: str, reread: bool = True) -> dict[str, Any]:
        """21.10: "לקחת את כל הערכים מהקורא החדש" – כל הסתירות מהקריאה מחדש בבת אחת."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        conf = ((rec["input"].get("ai_annual") or {}).get("conflicts") or {})
        paths = [p for p, c in conf.items() if bool(c.get("reread")) == reread]
        for p in paths:
            rec = self.resolve_ai(cid, p, choice)
        return rec

    def resolve_tb_ai(self, cid: str, row_id: str, choice: str) -> dict[str, Any]:
        """21.10: שורה במאזן הבוחן שהבודק השני סיווג אחרת – אברהם בוחר."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        conf = ((inp.get("ai_tb") or {}).get("conflicts") or {})
        c = conf.get(str(row_id))
        if not c or choice not in ("ours", "model"):
            raise ValueError("הסתירה כבר נסגרה")
        val = c[choice]
        if c.get("type") == "kind":
            m = dict(inp.get("tb_kind") or {}); m[str(row_id)] = val; inp["tb_kind"] = m
        else:
            m = dict(inp.get("tb_cogs") or {}); m[str(row_id)] = bool(val); inp["tb_cogs"] = m
        conf.pop(str(row_id), None)
        new = self.save(inp, cid)
        from .ai_check import KINDS
        shown = KINDS.get(val, val) if c.get("type") == "kind" else ("עלות מכר" if val else "לא עלות מכר")
        self._log(new, "תיקון", f"{c.get('name') or row_id}: נבחר {'OCR' if choice == 'ours' else 'AI'} – {shown}")
        return self._write(cid, new)

    def set_tb_cogs(self, cid: str, row_id: str, on: bool) -> dict[str, Any]:
        """אילו שורות במאזן הבוחן נכנסות לעלות המכר (שורת הרווח הגולמי)."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        inp = rec["input"]
        c = ((inp.get("ai_tb") or {}).get("conflicts") or {})
        if (c.get(str(row_id)) or {}).get("type") == "cogs":
            c.pop(str(row_id), None)
        m = dict(inp.get("tb_cogs") or {})
        m[str(row_id)] = bool(on)
        inp["tb_cogs"] = m
        new = self.save(inp, cid)
        name = next((r.get("name") for r in inp.get("tb_rows") or [] if str(r.get("id")) == str(row_id)), row_id)
        self._log(new, "תיקון", f"{name}: {'נכנס לעלות המכר' if on else 'הוצא מעלות המכר'} (רווח גולמי)")
        return self._write(cid, new)

    def adjust(self, cid: str, key: str, month, kind: str, amount: float = 0.0, note: str = "") -> dict[str, Any]:
        """אשר (accepted) / תקן (manual) / לא חסר (dismissed) / clear – לפריט אומדן או לחודש. תיקון תמיד גובר על האומדן."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        if kind not in ("accepted", "manual", "dismissed", "clear"):
            raise ValueError("סוג תיקון לא מוכר")
        inp = rec["input"]
        month = int(month) if month else None
        adj = [a for a in (inp.get("adjustments") or []) if not (a.get("key") == key and (a.get("month") or None) == month)]
        name = key
        if str(key).startswith("tb:"):
            rid = str(key)[3:]
            name = next((f"{r.get('name')} (מאזן בוחן)" for r in (inp.get("tb_rows") or []) if str(r.get("id")) == rid), key)
        label = f"{name}" + (f" · חודש {month}" if month else "")
        if kind != "clear":
            adj.append({"key": key, "month": month, "kind": kind, "amount": float(amount or 0), "note": note or "",
                        "by": self._by(), "at": datetime.now().isoformat(timespec="seconds")})
        inp["adjustments"] = adj
        new = self.save(inp, cid)
        txt = {"accepted": f"אומדן אושר: {label} – {float(amount or 0):,.0f} ₪", "manual": f"תיקון: {label} – {float(amount or 0):,.0f} ₪",
               "dismissed": f"לא חסר: {label}", "clear": f"בוטל תיקון: {label}"}[kind] + (f" ({note})" if note else "")
        self._log(new, "תיקון", txt)
        return self._write(cid, new)

    def mark_reviewed(self, cid: str, index: int, accept_pending: bool = False) -> dict[str, Any]:
        """אברהם עבר על קובץ: וי עם שם ותאריך. אופציונלי – לאשר בבת אחת את כל האומדנים שעוד ממתינים."""
        rec = self.get(cid)
        if not rec:
            raise ValueError("לקוח לא נמצא")
        srcs = rec.get("sources") or []
        if not (0 <= index < len(srcs)):
            raise ValueError("קובץ לא נמצא")
        if accept_pending:
            for it in (rec.get("result") or {}).get("estimate_items") or []:
                if it.get("status") == "pending":
                    rec = self.adjust(cid, it["key"], it.get("month"), "accepted", it.get("amount") or 0, "אושר בסימון 'נבדק'")
            srcs = rec.get("sources") or srcs
        srcs[index]["reviewed"] = {"by": self._by(), "at": datetime.now().isoformat(timespec="seconds"),
                                   "through_month": srcs[index].get("through_month")}
        rec["sources"] = srcs
        self._log(rec, "נבדק", f"{srcs[index].get('title', '')} {srcs[index].get('year') or ''} – נבדק")
        return self._write(cid, rec)

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

    def backfill_gross_history(self) -> int:
        """אברהם 15.10: לקוחות שנקלטו לפני שהוספנו את הרווח הגולמי של שנות הדוח – קוראים אותו מהדוח השנתי שכבר הועלה (פעם אחת)."""
        from .annual_report import parse_annual_report
        n = 0
        for rec in self.list():
            inp = rec.get("input") or {}
            s62 = inp.get("s62a") or {}
            bad = any(float(h.get("rate") or 0) > 1 for h in s62.get("gross_profit_history") or [])   # נקרא בטעות (לפני 1.5) – קוראים שוב
            if (s62.get("gross_profit_history") or inp.get("gp_checked")) and not bad:
                continue
            src = next((x for x in reversed(rec.get("sources") or []) if x.get("slot") == "annual_report" and not x.get("superseded")), None)
            p = Path(src.get("path") or "") if src else None
            hist = []
            if p and p.exists():
                try:
                    hist = parse_annual_report(p).get("fields", {}).get("s62a.gross_profit_history") or []
                except Exception:  # noqa: BLE001
                    hist = []
            full = self.get(rec["id"])
            if not full:
                continue
            full["input"].setdefault("s62a", {})["gross_profit_history"] = hist
            if bad:                                       # גם האחוז הממוצע (משמש להתאמת המלאי) נקרא מאותה שורה שגויה
                rates = [h["rate"] for h in hist if h.get("rate")]
                full["input"]["s62a"]["gross_margin_rate"] = round(sum(rates) / len(rates), 4) if rates else None
            full["input"]["gp_checked"] = True
            self.save(full["input"], rec["id"])
            n += 1
        return n

    def reread_reports(self, force: bool = False) -> dict[str, Any]:
        """21.10: אחרי עדכון של הקורא – קוראים שוב את הדוחות השנתיים השמורים (פעם אחת לכל גרסת קורא).
        ערך שונה ממה ששמור לא נדרס: נפתחת "סתירה" (שמור / הקורא החדש) ואברהם בוחר. שדה שאברהם הקליד – לא נוגעים."""
        from .annual_report import PARSER_VERSION
        from .ai_check import LABELS, _COMPANIONS, _SKIP, _same, _present
        from .importers import import_slot
        out = {"clients": 0, "changed": 0, "fields": 0, "names": []}
        for rec in self.list():
            if "input" not in rec or (rec.get("report_parser_version") == PARSER_VERSION and not force):
                continue
            src = next((x for x in reversed(rec.get("sources") or []) if x.get("slot") == "annual_report" and not x.get("superseded")), None)
            p = Path(src.get("path") or "") if src else None
            full = self.get(rec["id"])
            if not full:
                continue
            if not (p and p.exists()):
                full["report_parser_version"] = PARSER_VERSION      # אין קובץ שמור – אין מה לקרוא
                self._write(rec["id"], full)
                continue
            inp = full["input"]
            try:
                r = import_slot("annual_report", p, (inp.get("structure") or {}).get("tax_year"))
            except Exception as e:  # noqa: BLE001
                self._log(full, "קריאה מחדש", f"הדוח השנתי לא נקרא מחדש: {e}")
                full["report_parser_version"] = PARSER_VERSION
                self._write(rec["id"], full)
                continue
            out["clients"] += 1
            meta = full.get("field_meta") or {}
            now = datetime.now().isoformat(timespec="seconds")
            ai = inp.setdefault("ai_annual", {})
            conf = ai.setdefault("conflicts", {})
            n = 0
            for path, new in (r.get("fields") or {}).items():
                if path in _SKIP or path in conf:
                    continue
                if (meta.get(path) or {}).get("state") == "manual":
                    continue                                          # אברהם הקליד – לא נוגעים
                cur = self._get_path(inp, path)
                if path == "s62a.has_inventory":
                    if bool(cur) == bool(new):
                        continue
                elif not _present(new) or (_present(cur) and _same(path, cur, new)):
                    continue
                conf[path] = {"label": LABELS.get(path, path), "reread": True, "at": now,
                              "ours": cur, "ours_name": "שמור היום", "ours_src": (meta.get(path) or {}).get("source", ""),
                              "ours_also": {c: self._get_path(inp, c) for c in _COMPANIONS.get(path, ())},
                              "model": new, "model_name": "הקורא החדש", "model_src": (r.get("sources") or {}).get(path, "") + f" ({p.name})",
                              "model_also": {c: r["fields"][c] for c in _COMPANIONS.get(path, ()) if c in r["fields"]}}
                n += 1
            full["report_parser_version"] = PARSER_VERSION
            if n:
                ai.setdefault("at", now)
                new_rec = self.save(inp, rec["id"])
                new_rec["report_parser_version"] = PARSER_VERSION
                self._log(new_rec, "קריאה מחדש", f"הדוח השנתי נקרא שוב בגרסה החדשה של הקורא: {n} ערכים שונים ממה ששמור – לבחירה (לא נדרסו)")
                self._write(rec["id"], new_rec)
                out["changed"] += 1
                out["fields"] += n
                out["names"].append((inp.get("structure") or {}).get("name") or rec["id"])
            else:
                self._write(rec["id"], full)
        return out

    def backfill_ledger_months(self) -> int:
        """22.10: מבחן הריכוזיות לפי החוק סופר חודשי שירות – לכרטסות שנקלטו לפני כן, קוראים שוב את העותק השמור ומוסיפים חודשים."""
        from .importers import parse_ledger
        field = {"ledger": "top_customers", "ledger_prev": "top_customers_prev_year", "ledger_prev2": "top_customers_prev2_year"}
        n = 0
        for rec in self.list():
            inp = rec.get("input") or {}
            s62 = inp.get("s62a") or {}
            todo = [(slot, f) for slot, f in field.items() if s62.get(f) and not any("months" in c for c in s62.get(f) or [])]
            if not todo:
                continue
            full = self.get(rec["id"])
            changed = False
            for slot, f in todo:
                src = next((x for x in reversed(full.get("sources") or []) if x.get("slot") == slot and not x.get("superseded")), None)
                p = Path(src.get("path") or "") if src else None
                if not (p and p.exists()):
                    continue
                try:
                    tc = {c["name"]: c.get("months", []) for c in parse_ledger(p)["fields"]["s62a.top_customers"]}
                except Exception:  # noqa: BLE001
                    continue
                for c in full["input"]["s62a"].get(f) or []:
                    c["months"] = tc.get(c.get("name"), [])
                changed = True
            if changed:
                self.save(full["input"], rec["id"])
                n += 1
        return n

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
