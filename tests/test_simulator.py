"""החלטות 9–12: סימולציה, השפעת שכר על 81, מס דיבידנד ללקוח, המלצה מנוסחת."""

from __future__ import annotations

import json
from pathlib import Path

from trapped_profits import compute
from trapped_profits.engine import what_if
from trapped_profits.models import ClientInput

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"


def _ci() -> ClientInput:
    return ClientInput.from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8")))


def test_what_if_dividend_reaches_exemption():
    base = compute(_ci())
    assert base.calc81.surtax > 0
    r = what_if(_ci(), extra_dividend=base.simulator.min_dividend)
    assert r.calc81.is_exempt and r.calc81.surtax == 0
    assert r.simulator.action_required is False


def test_what_if_salary_fixes_62a_and_raises_expense_shield():
    base = compute(_ci())
    r = what_if(_ci(), salary=base.s62a.attributed_income)
    assert abs(r.s62a.governing_profitability - 0.25) < 1e-9
    assert r.s62a.section_applies is False
    assert r.shields.expenses_current_adjusted == base.shields.expenses_current_adjusted + base.s62a.attributed_income
    assert r.calc81.surtax <= base.calc81.surtax


def test_salary_effect_reported_in_simulator():
    # בדוגמה מגן הנכסים הוא הקובע → השכר לא משנה את תוספת המס
    base = compute(_ci())
    assert base.simulator.surtax_if_salary_paid == base.calc81.surtax
    # כשמגן ההוצאות הוא הקובע – השכר מוריד את תוספת המס, ותואם לסימולציה המלאה
    ci = _ci(); ci.shields.total_assets_cost = 3_000_000
    r = compute(ci)
    assert r.simulator.surtax_if_salary_paid < r.calc81.surtax
    assert abs(r.simulator.surtax_if_salary_paid - what_if(ci, salary=r.s62a.attributed_income).calc81.surtax) < 1e-6


def test_dividend_tax_rate_is_per_client():
    ci = _ci(); ci.simulator.dividend_tax_rate = 0.30
    r = compute(ci)
    assert abs(r.simulator.dividend_tax_cost - 0.30 * r.simulator.gap_to_close) < 1e-6


def test_recommendation_text_has_numbers_for_both_tracks():
    t = compute(_ci()).simulator.recommendation_text
    assert "מסלול 81" in t and "מסלול 62א" in t
    assert "57,300" in t and "850,000" in t
    ci = _ci(); ci.structure.is_few_holders_company = False
    assert "אינו חל" in compute(ci).simulator.recommendation_text
