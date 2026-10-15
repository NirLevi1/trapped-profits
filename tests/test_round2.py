"""סבב 2 מאברהם (14.10, ערב): אומדנים, ריכוזיות 36 חודשים, בפועל→אומדן, פעולות כבר השנה."""
import json
from pathlib import Path

from trapped_profits.engine import compute
from trapped_profits.models import ClientInput

EX = Path(__file__).resolve().parents[1] / "examples" / "clients"


def _load(name: str) -> dict:
    return json.loads((EX / name).read_text(encoding="utf-8"))


def test_estimates_inventory_depreciation_missing_category():
    inp = _load("חברה ו – מלאי, נתונים עד אוגוסט.json")
    r = compute(ClientInput.from_dict(inp))
    kinds = [n.split(":")[0] for n in r.estimate_notes]
    assert kinds[:2] == ["פחת", "מלאי"] and "שכר · אוגוסט" in kinds
    # בפועל נשמר; האומדן השנתי = ×1.5 ואז ההתאמות (החורים החודשיים – שכר אוגוסט, שכירות אפריל – לפני ההכפלה)
    assert r.actuals["taxable_income"] == 2_600_000 and r.actuals["through_month"] == 8
    rev = 4_900_000 * 1.5
    cogs = rev * (1 - 0.41)
    purchases = 1_500_000 * 1.5
    expected = (2_600_000 - 52_225 - 3_952) * 1.5 - 61_646 - (cogs - purchases)
    assert abs(r.s62a.taxable_income_personal_effort - expected) < 1
    assert r.years_used["current_year"].startswith("2026 עד חודש 8")


def test_concentration_36_months_decides():
    inp = _load("חברה ו – מלאי, נתונים עד אוגוסט.json")
    r = compute(ClientInput.from_dict(inp))
    assert r.s62a.concentration_years == [2024, 2025, 2026]
    assert r.s62a.concentration_met_by_data and r.s62a.concentration_test_met
    assert abs(r.s62a.attributed_income - r.s62a.taxable_income_personal_effort) < 1     # ייחוס מלא
    assert "לפי כרטסות 2024–2026" in r.dashboard.status_62a
    # בלי השנה השלישית – לא מכריעים
    inp["s62a"]["top_customers_prev2_year"] = []
    r2 = compute(ClientInput.from_dict(inp))
    assert not r2.s62a.concentration_met_by_data and len(r2.s62a.concentration_years) == 2
    assert r2.s62a.attributed_income < r2.s62a.taxable_income_personal_effort
    # מתחת ל-70% על 36 חודשים – לא מתקיים גם עם שלוש שנים
    inp["s62a"]["top_customers_prev2_year"] = [{"name": 'לקוח גדול בע"מ', "amount": 100}]
    inp["s62a"]["prev2_year_revenue_for_concentration"] = 10_000_000
    r3 = compute(ClientInput.from_dict(inp))
    assert len(r3.s62a.concentration_years) == 3 and not r3.s62a.concentration_met_by_data


def test_next_year_notes_are_actions_this_year():
    inp = _load("חברה ו – מלאי, נתונים עד אוגוסט.json")
    r = compute(ClientInput.from_dict(inp))
    txt = " ".join(r.next_year_notes)
    assert "אומדן עודפים לתום 2026" in txt and "לחלק עוד ב-2026" in txt
    assert "ל-4 החודשים שנותרו" in txt          # נתונים עד חודש 8


def test_no_estimates_without_data():
    inp = _load("חברה א – חשופה בשני המסלולים.json")
    r = compute(ClientInput.from_dict(inp))
    assert r.estimate_notes == [] and r.annualization_factor == 1.0


def test_monthly_gaps_and_adjustments():
    inp = _load("חברה ו – מלאי, נתונים עד אוגוסט.json")
    r = compute(ClientInput.from_dict(inp))
    pend = {(i["key"], i["month"]): i for i in r.estimate_items if i["status"] == "pending"}
    assert ("שכר", 8) in pend and abs(pend[("שכר", 8)]["estimate"] - 52225) < 1
    assert ("שכירות", 4) in pend
    assert ("קניות", 8) not in pend                     # קניות לא נחשבות "חור"
    base = r.s62a.taxable_income_personal_effort
    # תיקון ידני גובר על האומדן; "לא חסר" מוריד את האומדן
    inp["adjustments"] = [{"key": "שכר", "month": 8, "kind": "manual", "amount": 70000},
                          {"key": "שכירות", "month": 4, "kind": "dismissed"},
                          {"key": "פחת", "month": None, "kind": "accepted", "amount": 61646}]
    r2 = compute(ClientInput.from_dict(inp))
    st = {(i["key"], i["month"]): i["status"] for i in r2.estimate_items}
    assert st[("שכר", 8)] == "corrected" and st[("שכירות", 4)] == "dismissed" and st[("פחת", None)] == "accepted"
    # ההבדל בהכנסה החייבת: (70,000 − 52,225) × 1.5 תוספת, פחות 3,952 × 1.5 שירד
    assert abs((base - r2.s62a.taxable_income_personal_effort) - ((70000 - 52225) * 1.5 - 3952 * 1.5)) < 2
    assert r2.data_breakdown["corrections_monthly"] == 70000


def test_store_adjust_and_sources(tmp_path):
    from trapped_profits.store import ClientStore
    s = ClientStore(tmp_path / "clients")
    inp = _load("חברה ו – מלאי, נתונים עד אוגוסט.json")
    src = {"slot": "trial_balance", "title": "מאזן בוחן", "year": 2026, "file": "tb.csv", "path": "/x/tb.csv", "fields": 10, "through_month": 8}
    rec = s.save(inp, sources=[src])
    assert rec["sources"][0]["reviewed"] is None
    rec = s.adjust(rec["id"], "שכר", 8, "accepted", 52225, "")
    assert rec["history"][-1]["kind"] == "תיקון"
    assert any(i["key"] == "שכר" and i["status"] == "accepted" for i in rec["result"]["estimate_items"])
    rec = s.mark_reviewed(rec["id"], 0, accept_pending=True)
    assert rec["sources"][0]["reviewed"]["by"] == "המשרד"
    assert all(i["status"] != "pending" for i in rec["result"]["estimate_items"])
    # קובץ חדש לאותו חריץ – הקודם מסומן "הוחלף", החדש לא נבדק
    rec = s.save(rec["input"], rec["id"], sources=[{**src, "file": "tb2.csv", "through_month": 11}])
    assert rec["sources"][0]["superseded"] and rec["sources"][1]["reviewed"] is None
