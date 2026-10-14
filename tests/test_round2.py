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
    assert kinds == ["פחת", "מלאי", "חסר השנה"]
    # בפועל נשמר; האומדן השנתי = ×1.5 ואז ההתאמות
    assert r.actuals["taxable_income"] == 2_600_000 and r.actuals["through_month"] == 8
    rev = 4_900_000 * 1.5
    cogs = rev * (1 - 0.41)
    purchases = 1_500_000 * 1.5
    expected = 2_600_000 * 1.5 - 61_646 - (cogs - purchases) - 46_386
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
