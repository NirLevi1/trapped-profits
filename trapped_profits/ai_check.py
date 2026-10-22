"""בודק שני (21.10): מודל שפה קורא את אותו מסמך בנפרד מהקורא שלנו, ומשווים.

- דוח שנתי: המודל קורא את קובץ ה-PDF ומחזיר את הערכים; ממפים אותם לשדות באותה דרך כמו הקורא שלנו.
  ערך זהה → מסומן "אומת"; ערך שונה → סתירה: השדה לא מתמלא ואברהם בוחר; ערך שרק אחד מצא → נלקח, עם הערה.
- מאזן בוחן (רווח והפסד): כבוי בהעלאה (21.10 – בניסוי לא תרם); הקוד נשאר לשימוש עתידי.
- אין מפתח / אין אינטרנט / נגמר הקרדיט → הכל עובד כרגיל, עם הודעה שהבדיקה השנייה לא רצה.
המפתח נשמר בהגדרות שבתיקיית הנתונים ולא במאגר הקוד.
"""
from __future__ import annotations

import base64
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5-5"
# 22.10: אם המודל לא זמין בחשבון – מנסים את הבא; המודל שעבד נשמר בהגדרות
MODEL_CHAIN = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-4-5", "claude-sonnet-4-5")
MAX_PDF_BYTES = 30 * 1024 * 1024

# ---------------------------------------------------------------- קריאה לשירות

class AIError(Exception):
    """שגיאה שמוצגת לאברהם כמו שהיא (בעברית)."""


class ModelUnavailable(AIError):
    pass


def _service_msg(body: str) -> str:
    try:
        return str((json.loads(body).get("error") or {}).get("message") or "")[:200]
    except Exception:  # noqa: BLE001
        return body[:200]


def _human_error(code: int, body: str) -> str:
    low = body.lower()
    if code == 401:
        return "המפתח לא תקין – לבדוק בהגדרות"
    if code == 403:
        return "למפתח אין הרשאה – לבדוק בהגדרות"
    if "credit balance" in low or "billing" in low or code == 402:
        return "נגמר הקרדיט בחשבון – צריך להטעין"
    if code == 429:
        return "יותר מדי בקשות כרגע – לנסות שוב בעוד דקה"
    if code in (500, 502, 503, 529) or "overloaded" in low:
        return "השירות עמוס כרגע – לנסות שוב מאוחר יותר"
    if code == 413 or "too large" in low:
        return "הקובץ גדול מדי לבדיקה השנייה"
    m = _service_msg(body)
    return f"שגיאה מהשירות ({code})" + (f": {m}" if m else "")


def call_model(key: str, content: list, tool: dict, model: str = DEFAULT_MODEL, timeout: int = 180, max_tokens: int = 4096) -> dict:
    """קריאה אחת למודל עם כלי מחייב – מחזיר את הקלט שהמודל מסר לכלי (מילון)."""
    if not key:
        raise AIError("אין מפתח – להגדיר בהגדרות")
    body = json.dumps({
        "model": model or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key.strip(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            txt = ""
        low = txt.lower()
        if e.code in (400, 404) and "model" in low and "credit" not in low:
            raise ModelUnavailable(_human_error(e.code, txt)) from None
        raise AIError(_human_error(e.code, txt)) from None
    except urllib.error.URLError:
        raise AIError("אין חיבור לאינטרנט (או שהשירות חסום ברשת המשרד)") from None
    except TimeoutError:
        raise AIError("הבדיקה השנייה לקחה יותר מדי זמן") from None
    for block in data.get("content") or []:
        if block.get("type") == "tool_use":
            return block.get("input") or {}
    raise AIError("המודל לא החזיר תשובה במבנה הצפוי")


def test_key(key: str, model: str = DEFAULT_MODEL) -> dict:
    """בודק את המפתח; אם המודל לא זמין בחשבון – מנסה את הבאים ברשימה ומחזיר את זה שעבד."""
    tool = {"name": "ok", "description": "confirm", "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}
    chain = [model] + [m for m in MODEL_CHAIN if m != model]
    last = ""
    for m in chain:
        try:
            call_model(key, [{"type": "text", "text": "Call the tool with ok=true."}], tool, m, timeout=40, max_tokens=50)
            return {"ok": True, "msg": "מחובר", "model": m}
        except ModelUnavailable as e:
            last = str(e)
            continue
        except AIError as e:
            return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": last or "אף מודל לא זמין בחשבון"}


# ---------------------------------------------------------------- דוח שנתי

_NUM = {"type": ["number", "null"]}
_YEAR_ITEMS = ("retained_earnings", "share_capital", "share_premium", "cash_and_equivalents", "short_term_deposits", "inventory",
               "revenue", "cost_of_sales", "gross_profit", "general_admin_expenses", "selling_marketing_expenses",
               "finance_expenses", "other_expenses", "dividend")

ANNUAL_TOOL = {
    "name": "report_values",
    "description": "Report the values read from the financial statements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {"type": ["string", "null"]},
            "report_year": {"type": ["integer", "null"]},
            "years": {"type": "array", "items": {"type": "object", "properties": {
                "year": {"type": "integer"},
                **{k: _NUM for k in _YEAR_ITEMS},
                "pages": {"type": "object", "description": "item name → page number where it was read", "additionalProperties": {"type": "integer"}},
            }, "required": ["year"]}},
            "fixed_assets": {"type": "object", "properties": {
                "cost_closing": _NUM, "net_book_value": _NUM, "depreciation_for_year": _NUM,
                "page": {"type": ["integer", "null"]}}},
            "doubts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["company_name", "report_year", "years", "fixed_assets"],
    },
}

ANNUAL_PROMPT = """You are an independent second reader of an Israeli company's annual financial statements (Hebrew, possibly scanned).
Read the whole document carefully and report the values with the report_values tool.
- report_year = the balance-sheet date year (current column). Give values for the current year and for the prior-year column.
- Amounts in shekels as plain numbers (if the report is in thousands, multiply by 1000). Expenses as positive numbers. null if the item does not appear.
- retained_earnings: closing balance in the balance sheet (יתרת רווח / עודפים / רווחים שנצברו). Negative if it is a deficit.
- cash_and_equivalents and short_term_deposits from the balance sheet (securities are NOT deposits).
- revenue: total revenue line of the profit-and-loss statement. cost_of_sales: עלות המכירות / עלות ההכנסות / עלות מתן השירותים (null if none). gross_profit only if printed.
- general_admin_expenses, selling_marketing_expenses, finance_expenses (the expenses line, not net of finance income), other_expenses: the P&L lines.
- dividend: declared/paid in that year (P&L "ייעוד רווחים"/"דיבידנד" line or equity statement); 0 if the retained-earnings roll-forward shows none.
- fixed_assets: cost_closing = closing COST balance in the fixed-assets note (total column), null if there is no such note; net_book_value from the balance sheet;
  depreciation_for_year = depreciation for the current year per the fixed-assets note, or the "פחת" expense line if there is no note.
- company_name exactly as printed. Put anything you are unsure of in doubts (Hebrew)."""


def read_annual(pdf: str | Path, key: str, model: str = DEFAULT_MODEL, caller: Callable | None = None) -> dict:
    p = Path(pdf)
    data = p.read_bytes()
    if len(data) > MAX_PDF_BYTES:
        raise AIError("הקובץ גדול מדי לבדיקה השנייה")
    content = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode("ascii")}},
               {"type": "text", "text": ANNUAL_PROMPT}]
    return (caller or call_model)(key, content, ANNUAL_TOOL, model)


def _v(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def model_annual_fields(m: dict, tax_year: int | None) -> tuple[dict, dict, int | None]:
    """תשובת המודל → אותם שדות שהקורא שלנו ממלא (אותו מיפוי לפי שנת המס)."""
    from .annual_report import map_annual_fields
    Y = m.get("report_year")
    years = {int(y["year"]): y for y in (m.get("years") or []) if y.get("year")}
    by_year: dict[str, dict[int, float]] = {"retained": {}, "expenses": {}, "dividend": {}, "cash": {}, "capital": {}}
    src_raw: dict[str, str] = {}
    def pg(y: dict, *ks: str) -> str:
        pages = y.get("pages") or {}
        ps = sorted({pages[k] for k in ks if pages.get(k)})
        return f" (עמוד {', '.join(map(str, ps))})" if ps else ""
    for yr, y in years.items():
        if _v(y.get("retained_earnings")) is not None:
            by_year["retained"][yr] = _v(y["retained_earnings"])
            src_raw.setdefault("retained", "עודפים" + pg(y, "retained_earnings"))
        exp_keys = ("cost_of_sales", "general_admin_expenses", "selling_marketing_expenses", "finance_expenses", "other_expenses")
        ev = [_v(y.get(k)) for k in exp_keys]
        if any(e is not None for e in ev):
            by_year["expenses"][yr] = sum(abs(e or 0) for e in ev)
            src_raw[f"expenses_{yr}"] = "עלות + הנהלה + מכירה + מימון + אחרות" + pg(y, *exp_keys)
        if _v(y.get("dividend")):
            by_year["dividend"][yr] = abs(_v(y["dividend"]))
            src_raw.setdefault("dividend", "דיבידנד" + pg(y, "dividend"))
        c = [_v(y.get("cash_and_equivalents")), _v(y.get("short_term_deposits"))]
        if any(x is not None for x in c):
            by_year["cash"][yr] = sum(x or 0 for x in c)
            src_raw.setdefault("cash", "מזומנים + פיקדונות" + pg(y, "cash_and_equivalents"))
        k = [_v(y.get("share_capital")), _v(y.get("share_premium"))]
        if any(x is not None for x in k):
            by_year["capital"][yr] = sum(x or 0 for x in k)
            src_raw.setdefault("capital", "הון מניות + פרמיה" + pg(y, "share_capital"))
    f, src = map_annual_fields(by_year, int(Y), tax_year, src_raw, []) if Y else ({}, {})
    fa = m.get("fixed_assets") or {}
    fpg = f" (עמוד {fa['page']})" if fa.get("page") else ""
    if _v(fa.get("cost_closing")):
        f["shields.total_assets_cost"] = abs(_v(fa["cost_closing"]))
        f["shields.total_assets_cost_is_net"] = False
        src["shields.total_assets_cost"] = "ביאור רכוש קבוע – עלות" + fpg
    elif _v(fa.get("net_book_value")):
        f["shields.total_assets_cost"] = abs(_v(fa["net_book_value"]))
        f["shields.total_assets_cost_is_net"] = True
        src["shields.total_assets_cost"] = "רכוש קבוע נטו מהמאזן (אין ביאור)" + fpg
    if _v(fa.get("depreciation_for_year")):
        f["shields.depreciation_annual_estimate"] = abs(_v(fa["depreciation_for_year"]))
        src["shields.depreciation_annual_estimate"] = "פחת השנה" + fpg
    cur = years.get(int(Y)) if Y else None
    if cur is not None:
        f["s62a.has_inventory"] = bool(_v(cur.get("inventory")))
    hist = []
    for yr, y in sorted(years.items()):
        g, r = _v(y.get("gross_profit")), _v(y.get("revenue"))
        if g and r and abs(g) <= abs(r):
            hist.append({"year": yr, "revenue": round(abs(r)), "gross_profit": round(abs(g)), "rate": round(abs(g) / abs(r), 4)})
    if hist:
        f["s62a.gross_profit_history"] = hist
        f["s62a.gross_margin_rate"] = round(sum(h["rate"] for h in hist) / len(hist), 4)
        src["s62a.gross_margin_rate"] = "; ".join(f"{h['year']}: {h['rate']:.1%}" for h in hist)
    if m.get("company_name"):
        f["structure.name"] = re.sub(r"\s+", " ", str(m["company_name"])).strip()
    if Y:
        f["structure.last_closed_report_year"] = int(Y)
    return f, src, (int(Y) if Y else None)


LABELS = {
    "structure.name": "שם החברה", "structure.last_closed_report_year": "שנת הדוח",
    "retained.balance_sheet_retained_earnings": "עודפים במאזן", "distributions.retained_at_start_day": "רווחים ליום התחילה",
    "shields.expenses_prev_year": "הוצאות שנה קודמת", "shields.expenses_prev2_year": "הוצאות שנתיים קודם",
    "distributions.dividend_in_determining_period": "דיבידנד בתקופה הקובעת", "shields.share_capital_and_premium": "הון מניות ופרמיה",
    "shields.special_loans_deposits_cash": "מזומנים ופיקדונות", "shields.total_assets_cost": "עלות הנכסים",
    "shields.depreciation_annual_estimate": "פחת שנתי", "s62a.has_inventory": "יש מלאי", "s62a.gross_margin_rate": "אחוז רווח גולמי",
}
# שדות שנבחרים יחד עם השדה הראשי
_COMPANIONS = {"shields.total_assets_cost": ("shields.total_assets_cost_is_net",), "s62a.gross_margin_rate": ("s62a.gross_profit_history",)}
_SKIP = {"shields.total_assets_cost_is_net", "s62a.gross_profit_history"}


def _norm_name(s: str) -> str:
    s = re.sub(r"[֑-ׇ]", "", s or "")
    s = s.replace("״", '"').replace("׳", "'")
    return re.sub(r"[\s\-–,.\"'()]", "", s)


def _same(path: str, a: Any, b: Any) -> bool:
    if path == "structure.name":
        return _norm_name(str(a)) == _norm_name(str(b))
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    fa, fb = _v(a), _v(b)
    if fa is None or fb is None:
        return fa == fb
    if path == "s62a.gross_margin_rate":
        return abs(fa - fb) <= 0.005
    return abs(fa - fb) <= max(3.0, 0.0005 * max(abs(fa), abs(fb)))


def _present(v: Any) -> bool:
    return v not in (None, "") and not (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0)


def compare_annual(ours: dict, our_src: dict, model_f: dict, model_src: dict) -> dict:
    """מחזיר: fields (מה נכנס), sources, conflicts {שדה: {...}}, stats."""
    fields, sources = dict(ours), dict(our_src)
    conflicts: dict[str, dict] = {}
    agree = only_ours = only_model = 0
    for path in sorted(set(ours) | set(model_f)):
        if path in _SKIP:
            continue
        a, b = ours.get(path), model_f.get(path)
        pa, pb = _present(a), _present(b)
        if path == "s62a.has_inventory":
            pa, pb = path in ours, path in model_f
        if not pa and not pb:
            continue
        if pa and pb:
            if _same(path, a, b):
                agree += 1
                sources[path] = (sources.get(path) or "") + " · ✓ אומת בבודק השני"
            else:
                conflicts[path] = {
                    "label": LABELS.get(path, path),
                    "ours": a, "ours_src": our_src.get(path, ""), "ours_also": {c: ours[c] for c in _COMPANIONS.get(path, ()) if c in ours},
                    "model": b, "model_src": model_src.get(path, ""), "model_also": {c: model_f[c] for c in _COMPANIONS.get(path, ()) if c in model_f},
                }
                fields.pop(path, None)
                for c in _COMPANIONS.get(path, ()):
                    fields.pop(c, None)
        elif pa:
            only_ours += 1
            sources[path] = (sources.get(path) or "") + " · הבודק השני לא מצא – לוודא"
        else:
            fields[path] = b
            if isinstance(b, (int, float)) and not isinstance(b, bool) and abs(b) < 100:     # הון מניות של שקל – לא מטרידים
                sources[path] = "בודק שני: " + (model_src.get(path) or "")
                continue
            only_model += 1
            for c in _COMPANIONS.get(path, ()):
                if c in model_f:
                    fields[c] = model_f[c]
            sources[path] = "בודק שני: " + (model_src.get(path) or "") + " · הקורא שלנו לא מצא – לוודא"
    return {"fields": fields, "sources": sources, "conflicts": conflicts,
            "stats": {"agree": agree, "conflicts": len(conflicts), "only_ours": only_ours, "only_model": only_model}}


def verify_annual(r: dict, pdf: str | Path, tax_year: int | None, key: str, model: str = DEFAULT_MODEL, caller: Callable | None = None) -> dict:
    """משנה את r במקום: שדות, מקורות, הערות, ומוסיף r['fields']['ai_annual'] (סתירות לבחירה)."""
    now = datetime.now().isoformat(timespec="seconds")
    try:
        m = read_annual(pdf, key, model, caller)
        mf, msrc, _ = model_annual_fields(m, tax_year)
    except AIError as e:
        r.setdefault("notes", []).append(f"בודק שני לא רץ: {e} – הערכים מהקורא שלנו בלבד, לבדוק ידנית")
        r["ai"] = {"ok": False, "msg": str(e)}
        r["fields"]["ai_annual"] = {"at": now, "ok": False, "msg": str(e), "conflicts": {}}
        return r
    except Exception as e:  # noqa: BLE001
        msg = f"שגיאה בבדיקה השנייה: {e}"
        r.setdefault("notes", []).append(msg + " – הערכים מהקורא שלנו בלבד")
        r["ai"] = {"ok": False, "msg": msg}
        r["fields"]["ai_annual"] = {"at": now, "ok": False, "msg": msg, "conflicts": {}}
        return r
    c = compare_annual(r.get("fields") or {}, r.get("sources") or {}, mf, msrc)
    r["fields"], r["sources"] = c["fields"], c["sources"]
    s = c["stats"]
    msg = f"בודק שני: {s['agree']} ערכים תואמים" + (f", {s['conflicts']} סתירות – אברהם בוחר" if s["conflicts"] else "") + \
          (f", {s['only_model'] + s['only_ours']} נמצאו רק אצל אחד – לוודא" if s["only_model"] + s["only_ours"] else "")
    r.setdefault("notes", []).append(msg)
    for d in (m.get("doubts") or [])[:6]:
        r["notes"].append("בודק שני – ספק: " + str(d))
    r["ai"] = {"ok": True, "msg": msg, **s}
    r["fields"]["ai_annual"] = {"at": now, "ok": True, "msg": msg, "conflicts": c["conflicts"]}
    return r


# ---------------------------------------------------------------- מאזן בוחן

KINDS = {"revenue": "הכנסה מהעסק", "other_income": "הכנסה אחרת", "fin_income": "הכנסת מימון"}

TB_TOOL = {
    "name": "classify_rows",
    "description": "Classify trial-balance rows.",
    "input_schema": {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "kind": {"type": ["string", "null"], "enum": ["revenue", "other_income", "fin_income", None]},
        "cogs": {"type": ["boolean", "null"]},
        "reason": {"type": "string"},
    }, "required": ["id"]}}}, "required": ["rows"]},
}

TB_PROMPT = """These are profit-and-loss rows from an Israeli company's trial balance (Hebrew), with the annual total so far.
For every INCOME row give kind:
 revenue = income from the company's ordinary business activity (sales, services, fees);
 other_income = grants (מענקים, incl. war grants), refunds/reimbursements, compensation, capital gains, other non-operating income;
 fin_income = interest, exchange-rate gains, securities gains, other finance income.
For every EXPENSE row give cogs = true if it is a direct cost of what the company sells (purchases, materials, subcontractors, direct project costs, import costs),
false for overheads (management salaries, rent, office, vehicles, professional fees, finance expenses, depreciation).
Answer for every row id with classify_rows. reason: a few Hebrew words, only when the row is ambiguous.
Rows (id | section | group | name | income/expense | annual total):
"""


def verify_tb(r: dict, key: str, model: str = DEFAULT_MODEL, cogs_default: Callable | None = None, caller: Callable | None = None) -> dict:
    """מאזן בוחן: שורה שהמודל מסווג אחרת → r['fields']['ai_tb'] = {conflicts: {row_id: {...}}}."""
    from .engine import _row_kind, _is_cogs_default
    now = datetime.now().isoformat(timespec="seconds")
    rows = ((r.get("fields") or {}).get("tb_rows")) or []
    if not rows:
        return r
    lines = []
    for x in rows:
        tot = sum(float(v or 0) for v in (x.get("months") or []))
        lines.append(f"{x.get('id')} | {x.get('section') or ''} | {x.get('group') or ''} | {x.get('name') or ''} | {'income' if x.get('income') else 'expense'} | {abs(tot):,.0f}")
    try:
        m = (caller or call_model)(key, [{"type": "text", "text": TB_PROMPT + "\n".join(lines)}], TB_TOOL, model, max_tokens=8000)
    except AIError as e:
        r.setdefault("notes", []).append(f"בודק שני לא רץ על מאזן הבוחן: {e}")
        r["ai"] = {"ok": False, "msg": str(e)}
        r["fields"]["ai_tb"] = {"at": now, "ok": False, "msg": str(e), "conflicts": {}}
        return r
    except Exception as e:  # noqa: BLE001
        msg = f"שגיאה בבדיקה השנייה: {e}"
        r.setdefault("notes", []).append(msg)
        r["ai"] = {"ok": False, "msg": msg}
        r["fields"]["ai_tb"] = {"at": now, "ok": False, "msg": msg, "conflicts": {}}
        return r
    ans = {str(a.get("id")): a for a in (m.get("rows") or [])}
    conflicts: dict[str, dict] = {}
    agree = 0
    for x in rows:
        rid = str(x.get("id"))
        a = ans.get(rid)
        if not a:
            continue
        if x.get("income"):
            ours = _row_kind(x)
            theirs = a.get("kind")
            if theirs in KINDS and ours in KINDS:
                if theirs == ours:
                    agree += 1
                else:
                    conflicts[rid] = {"type": "kind", "name": x.get("name"), "ours": ours, "model": theirs, "reason": a.get("reason") or ""}
        elif x.get("kind") == "expense" and a.get("cogs") is not None:
            ours = (cogs_default or _is_cogs_default)(x)
            if bool(a["cogs"]) == bool(ours):
                agree += 1
            else:
                conflicts[rid] = {"type": "cogs", "name": x.get("name"), "ours": bool(ours), "model": bool(a["cogs"]), "reason": a.get("reason") or ""}
    msg = f"בודק שני: {agree} שורות בסיווג זהה" + (f", {len(conflicts)} בסיווג שונה – מסומנות ⚠ בטבלה" if conflicts else "")
    r.setdefault("notes", []).append(msg)
    r["ai"] = {"ok": True, "msg": msg, "agree": agree, "conflicts": len(conflicts)}
    r["fields"]["ai_tb"] = {"at": now, "ok": True, "msg": msg, "conflicts": conflicts}
    return r


# ---------------------------------------------------------------- מבקר (22.10)
# אחרי שכל הקבצים בפנים: המודל רואה את הנתונים, המקורות והתוצאה ומחזיר ממצאים – לא משנה מספרים.

REVIEW_RULES = """Rules the calculation follows (Israeli trapped-profits law, as implemented and APPROVED by the firm – do not argue with them):
Tax year = the client's tax_year; previous year = tax_year − 1. Data are up to data_through_month; later months are estimated.
SECTION 81 (2% surtax on excess retained profits)
- Retained profits = retained earnings in the last closed balance sheet (end of previous year). If the closed report is 1–2 years old it is rolled forward: + profit of each open year × (1 − 23%) − that year's dividends (estimate).
- Exempt if retained ≤ 750,000 (split between related companies).
- Shield = max of: fixed 750,000; expenses shield = max(current-year expenses, average of the last 3 years' expenses) – expenses INCLUDE depreciation in all years (prior years from the closed report; current year adds the report's annual depreciation because the trial balance has none); assets shield = cost of fixed assets (by law COST; if the report has no fixed-asset note, net book value is used as a fallback and is flagged for confirmation).
- Excess = retained − governing shield (after transition reductions). Surtax = 2% × excess unless 6% of retained or 50% of excess is distributed by year end.
SECTION 62A (attribution of personal-effort income)
- Personal-effort revenue = business revenue only (finance income and other income – grants, refunds, compensation – are excluded).
- Taxable income from the activity = revenue − expenses (excluding finance/other income). Profitability = taxable ÷ personal-effort revenue.
- If profitability > 25% → the excess over 25% is attributed to the owner ("salary fix"), unless the 750K exemption applies (retained at end of previous year ≤ 750,000 and the owner controls no other company).
- Concentration path: one customer ≥ 70% of revenue over 36 months (customer ledgers) → FULL attribution regardless of profitability and of the 750K exemption.
- Ledger lines on generic accounts (cash, transfers, cheques, misc customers) are excluded from concentration.
TRIAL BALANCE: every P&L row × 12 months; future months estimated (seasonality from the previous year scaled to this year's pace, payment cycles, averages, run-rate); the year = sum of the 12 cells. Zero in a past month of a regular row = "gap", estimated until the accountant confirms.
Inventory companies: cost of sales from the report's gross margin ("inventory adjustment"); purchases are offset. Cost-of-sales marking affects only the displayed gross profit.
Salaries booked under "production costs" are NOT cost of sales by default (firm decision)."""

REVIEW_PROMPT = """You are a senior Israeli CPA reviewing an automated trapped-profits calculation (sections 81 and 62A) before it goes to the partner.
Look for what does not add up or what a careful reviewer would question: data that looks wrong or inconsistent between files, suspicious year-over-year jumps,
estimates (especially seasonal/average estimates distorted by one unusual month) that drive the result, classifications that change the outcome,
conclusions that depend on an assumption that must be confirmed. Only findings that could change the 81/62A outcome or materially change amounts.
Do NOT repeat items already listed in "already_shown_to_accountant" (missing fields, owner salary not entered, open estimate approvals) – they are shown separately.
Do NOT repeat findings in "dismissed_by_accountant" unless the numbers behind them changed materially.
Avoid pure speculation without a sign in the data. At most 6 findings, most important first; zero findings is fine.
Write in Hebrew. Each finding: a short title, one or two sentences, and what to check. Use report_findings."""

REVIEW_TOOL = {
    "name": "report_findings",
    "description": "Report review findings.",
    "input_schema": {"type": "object", "properties": {
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "field": {"type": "string", "description": "input/result path or trial-balance row name"},
            "title": {"type": "string"}, "finding": {"type": "string"}, "check": {"type": "string"},
        }, "required": ["severity", "title", "finding", "check"]}},
        "overall": {"type": "string"},
    }, "required": ["findings", "overall"]},
}


def review_packet(rec: dict) -> dict:
    import copy
    inp = copy.deepcopy(rec.get("input") or {})
    res = copy.deepcopy(rec.get("result") or {})
    for k in ("tb_rows", "tb_rows_prev_year"):
        if inp.get(k):
            inp[k] = [{"name": r.get("name"), "section": r.get("section"), "group": r.get("group"), "income": r.get("income"),
                       "months": [round(float(x or 0)) for x in r.get("months") or []]} for r in inp[k]]
    for k in ("ai_annual", "ai_tb", "adjustments"):
        inp.pop(k, None)
    mt = res.get("months_table")
    if mt:
        res["months_table"] = {"through_month": mt.get("through_month"), "annual": mt.get("annual"), "gross_history": mt.get("gross_history"),
                               "rows": [{"name": r["name"], "kind": r["kind"], "total_with_estimates": r["total"], "file_total": r.get("file_total"), "method": r.get("method")} for r in mt.get("rows") or []]}
    for k in ("months_gap_table", "data_breakdown"):
        res.pop(k, None)
    meta = rec.get("field_meta") or {}
    sources = {k: v.get("source") for k, v in meta.items() if v.get("source")}
    shown = list(rec.get("missing_human") or []) + [f"{x} – חושב עם אפס" for x in (res.get("missing_fields") or [])]
    shown += [f"אומדן ממתין לאישור: {i.get('label')}" for i in (res.get("estimate_items") or []) if i.get("status") == "pending"][:20]
    old = (rec.get("review") or {}).get("findings") or []
    dismissed = [{"title": f.get("title"), "field": f.get("field"), "finding": f.get("finding"), "state": f.get("state")} for f in old if f.get("state") in ("checked", "irrelevant")]
    return {"input": inp, "result": res, "field_sources": sources, "files": [{"title": s.get("title"), "file": s.get("file"), "year": s.get("year")} for s in rec.get("sources") or [] if not s.get("superseded")],
            "already_shown_to_accountant": shown, "dismissed_by_accountant": dismissed}


def review_client(rec: dict, key: str, model: str = DEFAULT_MODEL, caller: Callable | None = None) -> dict:
    pk = review_packet(rec)
    content = [{"type": "text", "text": REVIEW_RULES}, {"type": "text", "text": REVIEW_PROMPT},
               {"type": "text", "text": "CLIENT DATA (JSON):\n" + json.dumps(pk, ensure_ascii=False, default=str)}]
    m = (caller or call_model)(key, content, REVIEW_TOOL, model, timeout=240, max_tokens=4000)
    out = []
    for i, f in enumerate(m.get("findings") or []):
        if not isinstance(f, dict) or not f.get("finding"):
            continue
        out.append({"id": f"f{i}", "severity": f.get("severity") if f.get("severity") in ("high", "medium", "low") else "medium",
                    "field": str(f.get("field") or ""), "title": str(f.get("title") or ""), "finding": str(f.get("finding") or ""),
                    "check": str(f.get("check") or ""), "state": "open"})
    return {"findings": out[:6], "overall": str(m.get("overall") or "")}
