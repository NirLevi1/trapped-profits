"""ייבוא מקבצי ריווחית (משימה פתוחה 5 / הערת אברהם 20).

שני דוחות שריווחית מייצאת כ-CSV (טאבים, UTF-16):
  * "דוח מאזן בוחן יתרות - לפי חודשים" – רווח והפסד של השנה הנבדקת לפי חודשים
        → סך הכנסות, הכנסות מימון/אחרות, הוצאות, רווח, עד איזה חודש יש נתונים, רמזים (שכר, דמי ניהול)
  * "דוח כרטסת הנהלת חשבונות" של כרטיס ההכנסות – כל חשבונית לפי לקוח
        → הלקוחות הגדולים (ריכוזיות)

הפלט: {"kind", "fields": {נתיב-בטופס: ערך}, "hints": {...}, "notes": [...]} – הטופס ממלא ומסמן "מהקובץ, לאישור".
הדוח השנתי הסגור (PDF סרוק) נשאר הקלדה ידנית בפיילוט.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

_NUM = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?$")


def _num(s: str) -> float | None:
    s = s.strip().strip('"')
    if not _NUM.match(s):
        return None
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()-").replace(",", ""))
    return -v if neg else v


def _read(path: str | Path) -> list[list[str]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "cp1255"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("קידוד קובץ לא מוכר")
    return [[c.strip().strip('"').strip() for c in line.split("\t")] for line in text.splitlines()]


def detect(path: str | Path) -> str:
    head = " ".join(" ".join(r) for r in _read(path)[:8])
    if "מאזן בוחן" in head and "חודשים" in head:
        return "trial_balance"
    if "כרטסת" in head:
        return "ledger"
    return "unknown"


# ---------------------------------------------------------------------------
# מאזן בוחן לפי חודשים – רווח והפסד
# ---------------------------------------------------------------------------
_INCOME_SECTIONS = ("הכנסות",)
_FIN_INCOME = ("הכנסות מימון",)
_OTHER_INCOME = ("הכנסות אחרות", "רווחים אחרים")
# אברהם (סבב 2, 5–7): סעיפי הוצאה לבדיקת שלמות בין שנים
CATEGORIES = (
    ("שכר", ("שכר עבודה", "משכורת", "משכורות")),
    ("עלויות מעסיק", ("ביטוח לאומי", "תגמולים", "פיצויים", "קרן השתלמות", "פנסיה", "סוציאליות")),
    ("שכירות", ("שכר דירה", "שכירות", "דמי שכירות")),
    ("פחת", ("פחת",)),
    ("קבלני משנה", ("קבלני משנה", "קבלנים", "קבלן משנה", "עבודות חוץ")),
    ("קניות", ("קניות",)),
    ("דמי ניהול", ("דמי ניהול",)),
)


def categorize(name: str) -> str | None:
    for cat, keys in CATEGORIES:
        if any(k in name for k in keys):
            return cat
    return None


def parse_trial_balance(path: str | Path) -> dict[str, Any]:
    rows = _read(path)
    year = None
    m = re.search(r"מחודש\s*\d+/(\d{4})", " ".join(" ".join(r) for r in rows[:10]))
    if m:
        year = int(m.group(1))
    section = ""
    accounts: list[dict] = []
    for r in rows:
        cells = [c for c in r if c != ""]
        if not cells:
            continue
        nums = [_num(c) for c in cells]
        n_nums = sum(1 for x in nums if x is not None)
        if n_nums >= 13 and nums[0] is not None:
            label = cells[-1]
            if label.startswith("סה") or label.startswith(":סה"):
                continue
            total = nums[0]
            # סדר העמודות: סה"כ, דצמבר..ינואר, יתרת פתיחה, שם
            months = [x or 0.0 for x in nums[1:13]][::-1]      # ינואר..דצמבר
            accounts.append({"section": section, "name": label, "total": total, "months": months})
        elif n_nums == 0 and len(cells) == 1 and not cells[0].startswith("סה"):
            t = cells[0]
            if t in ("רווח והפסד", "קבוצה מאזן", "פריט מאזן", "סיווג מאזן") or t.startswith("סה"):
                continue
            if " - " in t and t.split(" - ")[-1].strip().isdigit():   # "הוצאות הפעלה - 80" – תת-קבוצה
                continue
            section = t
    if not accounts:
        raise ValueError("לא נמצאו שורות חשבון בקובץ – זה מאזן בוחן לפי חודשים?")

    def is_income(sec: str) -> bool:
        return sec.startswith("הכנסות") or sec.startswith("רווחים")

    revenue = fin_income = other_income = expenses = 0.0
    months_activity = [0.0] * 12
    rev_months = [0.0] * 12
    hints: dict[str, float] = defaultdict(float)
    breakdown: dict[str, float] = defaultdict(float)
    breakdown_m: dict[str, list[float]] = defaultdict(lambda: [0.0] * 12)
    for a in accounts:
        sec, tot = a["section"], a["total"]
        for i, v in enumerate(a["months"]):
            months_activity[i] += abs(v)
        if is_income(sec):
            v = -tot                                   # הכנסות בזכות (שלילי בדוח)
            if any(k in sec for k in _FIN_INCOME) or "ריבית" in a["name"]:
                fin_income += v
            elif any(k in sec for k in _OTHER_INCOME):
                other_income += v
            else:
                revenue += v
                for i, mv in enumerate(a["months"]):
                    rev_months[i] += -mv
        else:
            expenses += tot
            nm = a["name"]
            if "שכר עבודה" in nm or "משכורת" in nm:
                hints["salaries"] += tot
            if "דמי ניהול" in nm:
                hints["management_fees"] += tot
            if "פחת" in nm:
                hints["depreciation"] += tot
            cat = categorize(nm)
            if cat:
                breakdown[cat] += tot
                for i, mv in enumerate(a["months"]):
                    breakdown_m[cat][i] += mv
    last_rev_month = max((i + 1 for i, v in enumerate(rev_months) if abs(v) > 0.5), default=0)
    last_any_month = max((i + 1 for i, v in enumerate(months_activity) if v > 0.5), default=0)
    profit = revenue + fin_income + other_income - expenses
    months_without = [i + 1 for i, v in enumerate(rev_months[:last_rev_month]) if abs(v) <= 0.5]
    notes = [f"הכנסות עד {MONTHS[last_rev_month - 1] if last_rev_month else '—'}; תנועות אחרונות עד {MONTHS[last_any_month - 1] if last_any_month else '—'}"]
    if hints.get("management_fees"):
        notes.append(f"דמי ניהול {hints['management_fees']:,.0f} ₪ – אם לחברה בשליטת בעל השליטה: תשלום לחברה קשורה")
    if hints.get("salaries"):
        notes.append(f"שכר עבודה {hints['salaries']:,.0f} ₪ – אם זה שכר הבעלים, להזין ב\"שכר בעלים ששולם\"")
    fields = {
        "structure.tax_year": year,
        "data_through_month": last_rev_month or None,
        "s62a.total_revenue": round(revenue),
        "s62a.other_interest": round(fin_income),
        "s62a.taxable_income_personal_effort": round(max(0.0, profit)),
        "shields.expenses_current_year": round(expenses - hints.get("depreciation", 0.0)),
        "distributions.current_year_profit_estimate": round(profit),
        "s62a.purchases_current_year": round(breakdown["קניות"]) if breakdown.get("קניות") else None,
        "period_breakdown": {k: round(v) for k, v in breakdown.items()},
        "period_breakdown_months": {k: [round(x) for x in v] for k, v in breakdown_m.items()},
        "months_without_revenue": months_without,
    }
    if months_without:
        notes.append("חודשים בלי הכנסות: " + ", ".join(MONTHS[m - 1] for m in months_without) + " – לבדוק אם חסר קובץ/רישום")
    return {"kind": "trial_balance", "year": year, "fields": {k: v for k, v in fields.items() if v is not None},
            "hints": dict(hints), "notes": notes,
            "summary": {"revenue": revenue, "fin_income": fin_income, "other_income": other_income, "expenses": expenses, "profit": profit,
                        "accounts": len(accounts)}}


# ---------------------------------------------------------------------------
# כרטסת הכנסות – לפי לקוח
# ---------------------------------------------------------------------------
def parse_ledger(path: str | Path) -> dict[str, Any]:
    rows = _read(path)
    header_idx = next((i for i, r in enumerate(rows) if "חשבון נגדי" in r and "זכות" in r), None)
    if header_idx is None:
        raise ValueError("לא נמצאה כותרת הכרטסת (חשבון נגדי / זכות)")
    hdr = rows[header_idx]
    i_credit, i_debit, i_contra = hdr.index("זכות"), hdr.index("חובה"), hdr.index("חשבון נגדי")
    i_date = hdr.index("תאריך ערך") if "תאריך ערך" in hdr else None
    by_customer: dict[str, float] = defaultdict(float)
    years: dict[int, int] = defaultdict(int)
    n = 0
    for r in rows[header_idx + 1:]:
        if len(r) <= i_contra:
            continue
        credit, debit = _num(r[i_credit]), _num(r[i_debit])
        if credit is None and debit is None:
            continue
        name = re.sub(r"\s+\d+\s*$", "", r[i_contra]).strip()   # "מקאן תל אביב בע"מ  84" → בלי מספר הכרטיס
        if not name:
            continue
        by_customer[name] += (credit or 0.0) - (debit or 0.0)
        n += 1
        if i_date is not None and len(r) > i_date:
            m = re.search(r"/(\d{2,4})$", r[i_date].strip())
            if m:
                y = int(m.group(1))
                years[y + 2000 if y < 100 else y] += 1
    if not n:
        raise ValueError("לא נמצאו תנועות בכרטסת")
    total = sum(by_customer.values())
    top = sorted(by_customer.items(), key=lambda x: -x[1])[:5]
    customers = [{"name": k, "amount": round(v)} for k, v in top if v > 0]
    share = (top[0][1] / total) if total > 0 and top else 0.0
    year = max(years, key=years.get) if years else None
    return {"kind": "ledger", "year": year, "fields": {"s62a.top_customers": customers},
            "notes": [f"{n} תנועות, {len(by_customer)} לקוחות, סה\"כ {total:,.0f} ₪; הגדול ביותר {top[0][0]} – {share:.0%}" if top else ""],
            "summary": {"total": total, "customers": len(by_customer), "top_share": share}}


def import_files(paths: list[str | Path]) -> dict[str, Any]:
    """כמה קבצים בבת אחת → איחוד השדות. קובץ לא מזוהה מדווח ולא מפיל."""
    out: dict[str, Any] = {"fields": {}, "notes": [], "files": [], "errors": []}
    for p in paths:
        try:
            kind = detect(p)
            if kind == "trial_balance":
                r = parse_trial_balance(p)
            elif kind == "ledger":
                r = parse_ledger(p)
            else:
                out["errors"].append(f"{Path(p).name}: לא זוהה כמאזן בוחן לפי חודשים או כרטסת")
                continue
            out["fields"].update(r["fields"])
            out["notes"] += [f"{Path(p).name}: {x}" for x in r["notes"] if x]
            out["files"].append({"name": Path(p).name, "kind": kind})
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{Path(p).name}: {e}")
    return out


# ---------------------------------------------------------------------------
# שלושה "חריצים" בטופס – כל קובץ בנפרד (אברהם 14.10: "אופציה להעלות את שלושתם, אפשר כל אחד בנפרד")
# ---------------------------------------------------------------------------
SLOTS = {
    "annual_report": {"title": "דוח שנתי סגור (PDF)", "types": ("PDF (*.pdf;*.PDF)",),
                      "desc": "מאזן + רווח והפסד מבוקרים לשנה הקודמת. דיגיטלי או סרוק (זיהוי תווים)."},
    "trial_balance": {"title": "מאזן בוחן לפי חודשים (ריווחית)", "types": ("קובץ ריווחית (*.csv;*.CSV;*.txt)",),
                      "desc": "ריווחית → דוחות → מאזן בוחן יתרות לפי חודשים → ייצוא. רווח והפסד של השנה הנבדקת."},
    "ledger": {"title": "כרטסת הכנסות (ריווחית)", "types": ("קובץ ריווחית (*.csv;*.CSV;*.txt)",),
               "desc": "ריווחית → כרטסת של כרטיס ההכנסות → ייצוא. לקוחות גדולים לריכוזיות."},
    # תרחיש ב׳ – הדוח הסגור ישן בשנה: השנה הקודמת מגיעה ממאזן בוחן מלא (וכרטסת לריכוזיות על פני שנתיים)
    "trial_balance_prev": {"title": "מאזן בוחן לפי חודשים – השנה הקודמת (מלא)", "types": ("קובץ ריווחית (*.csv;*.CSV;*.txt)",),
                           "desc": "רק כשאין דוח סגור לשנה הקודמת: רווח השנה הקודמת לגלגול העודפים, והוצאות השנה הקודמת למגן.", "prev": True},
    "ledger_prev": {"title": "כרטסת הכנסות – השנה הקודמת", "types": ("קובץ ריווחית (*.csv;*.CSV;*.txt)",),
                    "desc": "ריכוזיות על פני 36 חודשים: 70% מלקוח אחד על סך שלוש השנים.", "conc": True},
    "ledger_prev2": {"title": "כרטסת הכנסות – שנתיים אחורה", "types": ("קובץ ריווחית (*.csv;*.CSV;*.txt)",),
                     "desc": "השנה השלישית למבחן 36 החודשים.", "conc": True},
}


def import_slot(slot: str, path: str | Path, tax_year: int | None = None) -> dict[str, Any]:
    """קובץ אחד לחריץ אחד. מוודא שהקובץ מתאים לחריץ; מה שלא נמצא – לא מוחזר.
    tax_year – שנת המס של הלקוח/הטופס: קובע איך עמודות הדוח השנתי ממופות (דוח ישן בשנה = תרחיש ב׳)."""
    if slot not in SLOTS:
        raise ValueError("חריץ לא מוכר")
    p = Path(path)
    if slot == "annual_report":
        if p.suffix.lower() != ".pdf":
            raise ValueError("הדוח השנתי צריך להיות PDF")
        from .annual_report import parse_annual_report, map_annual_fields
        r = parse_annual_report(p)
        if tax_year and r.get("year"):
            notes = [n for n in r["notes"] if "תרחיש ב" not in n and "אינו מוקדם" not in n]
            f, src = map_annual_fields(r["by_year"], r["year"], int(tax_year), r.get("raw_sources", {}), notes)
            keep = ("structure.", "shields.total_assets_cost", "shields.depreciation_annual_estimate", "s62a.has_inventory", "s62a.gross_margin_rate")
            base = {k: v for k, v in r["fields"].items() if k.startswith(keep)}
            f.update(base)
            src.update({k: v for k, v in r.get("sources", {}).items() if k in base})
            r["fields"], r["sources"], r["notes"] = f, src, notes
    else:
        kind = detect(p)
        base = slot.replace("_prev2", "").replace("_prev", "")
        if kind != base:
            names = {"trial_balance": "מאזן בוחן לפי חודשים", "ledger": "כרטסת", "unknown": "קובץ לא מזוהה"}
            raise ValueError(f"זה נראה כמו {names.get(kind, kind)} – לא {SLOTS[slot]['title']}")
        r = parse_trial_balance(p) if base == "trial_balance" else parse_ledger(p)
        want = (int(tax_year) - 2 if slot.endswith("_prev2") else int(tax_year) - 1 if slot.endswith("_prev") else int(tax_year)) if tax_year else None
        if want and r.get("year") and r["year"] != want:
            other = "השנה הקודמת" if r["year"] == (want - 1) else ("השנה הנבדקת" if r["year"] == want + 1 else str(r["year"]))
            raise ValueError(f"הקובץ הוא לשנת {r['year']} והחריץ הזה מצפה ל-{want} – אולי זה שייך לחריץ של {other}?")
        if slot == "trial_balance_prev":
            f = r["fields"]
            r["fields"] = {"shields.expenses_prev_year": f.get("shields.expenses_current_year", 0) + r.get("hints", {}).get("depreciation", 0),
                           "retained.prev_year_profit_for_rollover": f.get("distributions.current_year_profit_estimate", 0),
                           "period_breakdown_prev_year": f.get("period_breakdown", {})}
            r["sources"] = {"shields.expenses_prev_year": f"מאזן בוחן {r.get('year')}: סך הוצאות (כולל פחת)",
                            "retained.prev_year_profit_for_rollover": f"מאזן בוחן {r.get('year')}: רווח לפני מס – המנוע מגלגל: עודפי הדוח + רווח × (1 − 23%) − דיבידנד השנה הקודמת (ידני)"}
            r["notes"] = [n for n in r["notes"] if "הכנסות עד" not in n] + [f"גלגול: דיבידנד {r.get('year')} אינו במאזן בוחן – להזין ידנית אם חולק"]
        elif slot == "ledger_prev":
            r["fields"] = {"s62a.top_customers_prev_year": r["fields"]["s62a.top_customers"],
                           "s62a.prev_year_revenue_for_concentration": round(r["summary"]["total"])}
            r["sources"] = {"s62a.top_customers_prev_year": f"כרטסת {r.get('year')}"}
        elif slot == "ledger_prev2":
            r["fields"] = {"s62a.top_customers_prev2_year": r["fields"]["s62a.top_customers"],
                           "s62a.prev2_year_revenue_for_concentration": round(r["summary"]["total"])}
            r["sources"] = {"s62a.top_customers_prev2_year": f"כרטסת {r.get('year')}"}
    r["file"] = p.name
    r["slot"] = slot
    r.setdefault("sources", {})
    return r


def keep_copy(path: str | Path, client_dir: Path, slot: str) -> Path:
    """שומר עותק של הקובץ שהועלה: data/files/<לקוח>/<שנה>-Q<רבעון>/<חריץ> – <שם הקובץ>  (תיעוד להיסטוריה)."""
    import shutil
    from datetime import date
    d = date.today()
    q = (d.month - 1) // 3 + 1
    dst_dir = client_dir / f"{d.year}-Q{q}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    p = Path(path)
    dst = dst_dir / f"{slot} – {p.name}"
    shutil.copy2(p, dst)
    return dst
