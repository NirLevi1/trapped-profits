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


# ── (14.10 שלב ב) מצב שדות: מהקובץ / אושר / ידני / חסר; עדכון מקובץ בכרטיס ──
def test_field_meta_states_and_apply_import():
    from trapped_profits.store import HUMAN_ONLY_FIELDS
    s = ClientStore(Path(tempfile.mkdtemp()))
    rec = s.save(_inp(), field_meta={"retained.balance_sheet_retained_earnings": {"state": "file", "source": "רווח שנצבר"}})
    assert rec["pending_file_fields"] == ["retained.balance_sheet_retained_earnings"]
    assert len(rec["missing_human"]) == len(HUMAN_ONLY_FIELDS)          # עוד לא נגעו באף שדה "רק אדם יודע"
    # עריכה ישירה = ידני → יוצא מהחסרים
    rec = s.update_field(rec["id"], "structure.company_id", "515000001")
    assert "מספר ח.פ." not in rec["missing_human"] and rec["field_meta"]["structure.company_id"]["state"] == "manual"
    # אישור הכל
    rec = s.approve_fields(rec["id"])
    assert rec["pending_file_fields"] == [] and rec["field_meta"]["retained.balance_sheet_retained_earnings"]["state"] == "approved"
    # עדכון רבעוני מקובץ בכרטיס: דורס רק את השדות שבקובץ, מסמן "מהקובץ", רושם בהיסטוריה
    before = rec["input"]["structure"]["company_id"]
    rec = s.apply_import(rec["id"], {"s62a.total_revenue": 999_000, "data_through_month": 9}, {"s62a.total_revenue": "4 הכנסות"}, "מאזן בוחן")
    assert rec["input"]["s62a"]["total_revenue"] == 999_000 and rec["input"]["data_through_month"] == 9
    assert rec["input"]["structure"]["company_id"] == before
    assert rec["field_meta"]["s62a.total_revenue"]["state"] == "file" and rec["pending_file_fields"] == ["s62a.total_revenue", "data_through_month"]
    assert rec["history"][-1]["kind"] == "עדכון מקובץ"
    # מצב לא חוקי לא נשמר
    rec = s.save(rec["input"], rec["id"], field_meta={"s62a.total_revenue": {"state": "bogus"}})
    assert rec["field_meta"]["s62a.total_revenue"]["state"] == "file"


# ── תרחיש ב׳ עם גלגול אוטומטי (דוח סגור 2024, מאזן בוחן 2025 מלא, שנת מס 2026) ──
def test_scenario_b_rollover_from_prev_year_trial_balance():
    d = _inp()
    d["structure"].update(tax_year=2026, last_closed_report_year=2024)
    d["retained"]["balance_sheet_retained_earnings"] = 4_296_517      # עודפי הדוח הסגור 2024
    d["retained"]["prev_year_profit_for_rollover"] = 1_601_899        # רווח 2025 לפני מס (מאזן בוחן)
    d["distributions"]["dividends_prev_year"] = 500_000
    r = compute(ClientInput.from_dict(d))
    assert r.is_estimate
    expected = 4_296_517 + 1_601_899 * 0.77 - 500_000
    assert abs(r.retained.accounting_cap - expected) < 1 and "גלגול" in r.retained.rollover_note
    # בלי רווח לגלגול – העודפים כמו שהוזנו
    d["retained"]["prev_year_profit_for_rollover"] = None
    r2 = compute(ClientInput.from_dict(d))
    assert abs(r2.retained.accounting_cap - 4_296_517) < 1 and r2.retained.rollover_note == ""
    # לא תרחיש ב׳ – הגלגול לא פעיל גם אם הוזן רווח
    d["structure"]["last_closed_report_year"] = 2025
    d["retained"]["prev_year_profit_for_rollover"] = 1_601_899
    assert abs(compute(ClientInput.from_dict(d)).retained.accounting_cap - 4_296_517) < 1


def test_prev_year_concentration_uses_prev_total():
    d = _inp()
    d["s62a"]["total_revenue"] = 1_000_000
    d["s62a"]["top_customers"] = [{"name": "א", "amount": 800_000}]
    d["s62a"]["top_customers_prev_year"] = [{"name": "א", "amount": 300_000}, {"name": "ב", "amount": 100_000}]
    d["s62a"]["prev_year_revenue_for_concentration"] = 2_000_000
    r = compute(ClientInput.from_dict(d))
    assert abs(r.s62a.concentration_share - 0.8) < 1e-9 and abs(r.s62a.concentration_share_prev_year - 0.15) < 1e-9
