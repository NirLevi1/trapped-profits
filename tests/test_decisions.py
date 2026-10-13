"""החלטות 4–6 מהריאיון: אומדן שנתי, חסר נתון, סימון שינוי בחישוב מחדש."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from trapped_profits import compute
from trapped_profits.models import ClientInput
from trapped_profits.store import ClientStore

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"


def _ci() -> ClientInput:
    return ClientInput.from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8")))


# --- החלטה 4: אומדן שנתי לינארי ---------------------------------------------
def test_annualization_scales_flows_not_balances():
    full = compute(_ci())
    ci = _ci()
    # אותם נתונים אבל "עד חודש 6" → המנוע מכפיל ×2
    ci.data_through_month = 6
    for k in ("total_revenue", "other_interest", "other_rent", "taxable_income_personal_effort"):
        setattr(ci.s62a, k, getattr(ci.s62a, k) / 2)
    ci.shields.expenses_current_year /= 2
    half = compute(ci)
    assert half.annualization_factor == 2.0
    assert half.s62a.personal_effort_income == full.s62a.personal_effort_income
    assert half.s62a.governing_profitability == full.s62a.governing_profitability
    assert half.shields.expenses_shield == full.shields.expenses_shield
    # יתרות מאזן ודיבידנדים לא מוכפלים
    assert half.retained.retained_for_81a == full.retained.retained_for_81a
    assert half.calc81.surtax == full.calc81.surtax


def test_annualization_ignored_for_full_year():
    ci = _ci(); ci.data_through_month = 12
    assert compute(ci).annualization_factor == 1.0
    ci.data_through_month = None
    assert compute(ci).annualization_factor == 1.0


# --- החלטה 5: חסר נתון → מחשבים ומזהירים ------------------------------------
def test_missing_fields_warn_but_compute():
    ci = _ci()
    ci.s62a.total_revenue = 0
    ci.shields.expenses_current_year = 0
    res = compute(ci)
    assert "סך ההכנסות" in res.missing_fields
    assert "הוצאות השנה הנבדקת" in res.missing_fields
    assert res.dashboard.status_overall  # עדיין יש תוצאה


def test_no_missing_on_full_input():
    assert compute(_ci()).missing_fields == []


# --- החלטה 6: חישוב מחדש מסמן מה השתנה ----------------------------------------
def test_recompute_marks_changes():
    store = ClientStore(Path(tempfile.mkdtemp()))
    inp = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    first = store.save(inp)
    assert first["changes"] == []                       # חישוב ראשון
    same = store.save(inp, first["id"])
    assert same["changes"] == []                        # אותו קלט → אין שינוי
    inp["distributions"]["dividends_taxed_current_year"] = 450_000   # עומד ב-6%
    changed = store.save(inp, first["id"])
    whats = {c["what"] for c in changed["changes"]}
    assert {"תוספת מס", "פער לחלוקה"} <= whats
    assert "סטטוס כולל" not in whats                    # עדיין אדום בגלל 62א
    assert store.recompute_all() == 1
