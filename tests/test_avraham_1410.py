"""הערות אברהם מפגישת 14.10: מדרגות מס לשכר, ריכוזיות, תווית מצב 81, סימולטור רק כשנדרש, היסטוריה, עריכת שדה."""
import json, tempfile
from pathlib import Path

from trapped_profits import compute, ClientInput
from trapped_profits.engine import _individual_tax, TAX_BRACKETS_2025
from trapped_profits.store import ClientStore
from trapped_profits.documents import build_accountant_doc, build_client_doc, render_html

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"


def _inp():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


# ── (10) עלות מס נוספת לפי מדרגות ──
def test_tax_brackets_basic():
    assert _individual_tax(0) == 0
    assert abs(_individual_tax(84_120) - 8_412) < 1e-6
    assert abs(_individual_tax(100_000) - (8_412 + 15_880 * 0.14)) < 1e-6
    # מעל המדרגה העליונה – 50% שולי
    assert abs((_individual_tax(2_000_000) - _individual_tax(1_000_000)) - 500_000) < 1e-6
    assert TAX_BRACKETS_2025[-1][1] == 0.50


def test_extra_tax_cost_uses_brackets_when_salary_given():
    d = _inp()
    d["s62a"]["owner_salary_current_year"] = None
    r0 = compute(ClientInput.from_dict(d))
    assert r0.s62a.attributed_income > 0 and "מס שולי" in r0.s62a.extra_tax_cost_method
    d["s62a"]["owner_salary_current_year"] = 360_000
    r1 = compute(ClientInput.from_dict(d))
    a = r1.s62a.attributed_income
    expected = _individual_tax(360_000 + a) - _individual_tax(360_000) - 0.23 * a
    assert abs(r1.s62a.extra_tax_cost - expected) < 1
    assert "מדרגות" in r1.s62a.extra_tax_cost_method
    # שכר נמוך → חלק מההכנסה המיוחסת נופל במדרגות נמוכות → זול יותר מאשר 27% אחיד
    d["s62a"]["owner_salary_current_year"] = 0
    r2 = compute(ClientInput.from_dict(d))
    assert r2.s62a.extra_tax_cost < r0.s62a.extra_tax_cost


# ── (12) ריכוזיות ──
def test_concentration_breakdown_and_warning():
    d = _inp()
    rev = d["s62a"]["total_revenue"]
    d["s62a"]["top_customers"] = [{"name": "א", "amount": rev * 0.6}, {"name": "ב", "amount": rev * 0.1}]
    r = compute(ClientInput.from_dict(d))
    assert abs(r.s62a.concentration_share - 0.6) < 1e-9 and r.s62a.concentration_top_name == "א"
    names = [x["name"] for x in r.s62a.customers_breakdown]
    assert names == ["א", "ב", "אחרים"] and abs(sum(x["share"] for x in r.s62a.customers_breakdown) - 1) < 1e-9
    d["s62a"]["top_customers"] = [{"name": "א", "amount": rev * 0.75}]
    d["s62a"]["taxable_income_personal_effort"] = rev * 0.1      # רווחיות נמוכה – כדי שהריכוזיות תקבע את הצבע
    r = compute(ClientInput.from_dict(d))
    assert r.dashboard.color_62a == "צהוב" and "ריכוזיות" in r.dashboard.status_62a
    assert any("ריכוזיות" in m for m in r.manual_review)


def test_concentration_annualized_with_partial_year():
    d = _inp()
    rev = d["s62a"]["total_revenue"]
    d["s62a"]["top_customers"] = [{"name": "א", "amount": rev * 0.5}]
    d["data_through_month"] = 6
    r = compute(ClientInput.from_dict(d))
    assert abs(r.s62a.concentration_share - 0.5) < 1e-9     # שניהם הוכפלו – היחס נשמר


# ── (6, 7) תווית מצב 81 וסימולטור ──
def test_status_label_and_simulator_relevance():
    d = _inp()
    r = compute(ClientInput.from_dict(d))
    assert r.calc81.status_label == "חייב בתוספת מס" and r.simulator.action_required
    d["distributions"]["dividends_taxed_current_year"] = r.simulator.min_dividend
    r2 = compute(ClientInput.from_dict(d))
    assert r2.calc81.status_label.startswith("פטור – ") and not r2.simulator.action_required
    d["structure"]["is_few_holders_company"] = False
    assert compute(ClientInput.from_dict(d)).calc81.status_label == "החוק אינו חל"


def test_alternative_shown_only_with_exempt_sources():
    d = _inp()
    assert not compute(ClientInput.from_dict(d)).calc81.alternative_relevant
    d["retained"]["exempt_industrial_sales_income"] = 100_000
    assert compute(ClientInput.from_dict(d)).calc81.alternative_relevant


# ── (22) שנה הבאה ──
def test_next_year_notes_present():
    r = compute(ClientInput.from_dict(_inp()))
    assert r.next_year_notes and any(str(r.tax_year + 1) in n for n in r.next_year_notes)


# ── (16, 18, 19, 3, 15) אחסון: היסטוריה, הערה למכתב, עריכת שדה ──
def test_history_letter_note_and_update_field():
    s = ClientStore(Path(tempfile.mkdtemp()))
    rec = s.save(_inp())
    assert [h["kind"] for h in rec["history"]] == ["חישוב"]
    s.set_handling(rec["id"], "בשיחה", "דיברנו")
    s.set_letter_note(rec["id"], "בהמשך לשיחתנו – נחלק 430 אלף")
    rec2 = s.update_field(rec["id"], "retained.balance_sheet_retained_earnings", 1_000_000)
    assert rec2["input"]["retained"]["balance_sheet_retained_earnings"] == 1_000_000
    assert [h["kind"] for h in rec2["history"]] == ["חישוב", "טיפול", "הערה למכתב", "חישוב"]
    assert rec2["letter_note"].startswith("בהמשך")
    rec3 = s.update_field(rec["id"], "s62a.owner_salary_current_year", 300_000)
    assert "מדרגות" in rec3["result"]["s62a"]["extra_tax_cost_method"]
    try:
        s.update_field(rec["id"], "s62a.no_such_field", 1)
        assert False
    except ValueError:
        pass
    # מסמכים עם ההערה וההיסטוריה
    r = compute(ClientInput.from_dict(rec3["input"]))
    html = render_html(build_client_doc(r, "משרד", "רו\"ח", letter_note=rec3["letter_note"]))
    assert "בהמשך לשיחתנו" in html
    html = render_html(build_accountant_doc(r, rec3["handling"], rec3["history"]))
    assert "היסטוריה" in html and "הקובע" in html
