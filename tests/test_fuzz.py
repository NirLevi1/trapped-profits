"""בדיקת עומס אקראית: אלפי לקוחות עם מספרים משונים – המנוע לא קורס, והתוצאות מקיימות כללים שחייבים להתקיים תמיד."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from trapped_profits import compute
from trapped_profits.documents import build_accountant_doc, build_client_doc, render_html
from trapped_profits.engine import what_if
from trapped_profits.models import ClientInput

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"


def rnd_client(rng: random.Random, i: int) -> ClientInput:
    d = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    m = rng.choice([0, 1e3, 1e5, 1e6, 1e7, 5e7])        # סדר גודל
    f = lambda lo=0.0, hi=1.0: rng.uniform(lo, hi) * m  # noqa: E731
    st, r, sh, di, s = d["structure"], d["retained"], d["shields"], d["distributions"], d["s62a"]
    st.update(name=f"לקוח {i}", company_id=str(510000000 + i), tax_year=rng.choice([2025, 2026, 2027]),
              last_closed_report_year=rng.choice([None, 2023, 2024, 2025]),
              is_few_holders_company=rng.random() < 0.9, preferred_or_approved_enterprise=rng.random() < 0.1,
              controlling_owners_count=rng.choice([0, 1, 1, 2, 3]), group_companies_count=rng.choice([1, 1, 2, 4]),
              group_companies_waived=rng.choice([0, 0, 1]), owner_controls_another_company=rng.random() < 0.4,
              partnership_income_share=rng.choice([0, 0, 0.05, 0.3]))
    r.update(cumulative_taxable_income=rng.choice([None, 0, f(0, 3)]), cumulative_tax=f(0, 0.7), cumulative_dividends=f(0, 1),
             balance_sheet_retained_earnings=f(0, 2), attributed_to_shareholders=f(0, 0.1),
             exempt_industrial_sales_income=rng.choice([0, 0, f(0, 1)]), exempt_profits_last_7_years=rng.choice([0, f(0, 0.5)]))
    sh.update(expenses_current_year=f(0, 1), expenses_prev_year=f(0, 1), expenses_prev2_year=f(0, 1),
              pay_62a_salary_by_year_end=rng.random() < 0.3, total_assets_cost=f(0, 3),
              special_securities=f(0, 0.5), special_real_estate=f(0, 0.5), special_loans_deposits_cash=f(0, 0.5),
              excl_own_use_real_estate=f(0, 0.3), share_capital_and_premium=f(0, 0.05), related_party_loan=f(0, 0.2),
              held_company_cost=rng.choice([0, 0, f(0, 0.3)]))
    di.update(dividends_taxed_current_year=rng.choice([0, 0, f(0, 0.5)]), losses_current_year=rng.choice([0, 0, 0, f(0, 0.3)]),
              excess_profits_prev_year=rng.choice([0, f(0, 1)]), start_day_excess_profits=rng.choice([0, f(0, 1)]),
              start_day_dividends_taxed=f(0, 0.3), retained_at_start_day=rng.choice([0, f(0, 2)]),
              dividend_in_determining_period=f(0, 2), determining_period_paid_and_taxed=rng.random() < 0.5,
              current_year_profit_estimate=rng.choice([None, f(-0.5, 1)]))
    s.update(total_revenue=rng.choice([0, f(0, 5)]), other_interest=f(0, 0.05), other_rent=f(0, 0.1), other_dividend=rng.choice([0, f(0, .1)]),
             taxable_income_personal_effort=f(0, 1.5), related_company_payments=rng.choice([0, 0, f(0, 0.2)]),
             avg_profitability_2023_2025=rng.choice([0, 0.18, 0.3]), concentration_test_met=rng.random() < 0.1,
             intercompany_dividend_received=rng.choice([0, 0, f(0, .2)]), holding_rate_in_paying_company=rng.choice([None, 0.05, 0.5]),
             marginal_tax_rate=rng.choice([0.3, 0.47, 0.5]))
    d["simulator"]["dividend_tax_rate"] = rng.choice([0, 0.3, 0.33])
    d["data_through_month"] = rng.choice([None, 0, 1, 6, 11, 12, 13])
    return ClientInput.from_dict(d)


def _invariants(r):
    k, s, m = r.calc81, r.s62a, r.simulator
    assert k.surtax >= 0 and k.excess_profits >= 0 and k.surtax_base >= 0
    assert abs(k.surtax - (0 if (k.is_exempt or not r.applies_81) else 0.02 * k.surtax_base)) < 1e-6
    assert k.excess_profits == min(k.excess_alt1, k.excess_alt2)
    assert 0 <= s.governing_profitability or s.personal_effort_income == 0
    assert s.attributed_income >= 0 and s.extra_tax_cost >= 0
    assert m.min_dividend >= 0 and m.gap_to_close >= 0 and m.gap_to_close <= m.min_dividend + 1e-6
    assert m.action_required == (k.surtax > 0)
    assert r.dashboard.color_overall in ("ירוק", "צהוב", "אדום")
    if not r.applies_81:
        assert k.surtax == 0 and r.dashboard.color_81 == "ירוק"
    if not r.applies_62a:
        assert s.attributed_income == 0
    if r.retained.exempt_sources_total <= 0:
        assert k.chosen_alternative == 2
    assert m.recommendation_text
    assert r.annualization_factor >= 1.0


@pytest.mark.parametrize("seed", range(8))
def test_fuzz_engine(seed):
    rng = random.Random(seed)
    for i in range(400):
        ci = rnd_client(rng, i)
        r = compute(ci)
        _invariants(r)
        json.dumps(r.to_dict(), ensure_ascii=False)        # ניתן לשמירה
        # סימולציה: דיבידנד מספיק תמיד מגיע לפטור (אם החוק חל ויש בסיס)
        if r.applies_81 and r.calc81.surtax > 0:
            w = what_if(ci, extra_dividend=r.simulator.min_dividend)
            assert w.calc81.is_exempt, (seed, i)
        # שכר בגובה ההכנסה המיוחסת תמיד מוריד ל-25% או מתחת
        # (לפי הסיכום הניכוי הוא 25% מההכנסה בלי תשלומים לחברה קשורה – לכן התשלומים נשארים מעל הסף; נקודה 6 לאברהם)
        if r.applies_62a and r.s62a.section_applies and not ci.s62a.concentration_test_met and not ci.data_through_month:
            w = what_if(ci, salary=r.s62a.attributed_income)
            allowed = 0.25 + ci.s62a.related_company_payments / max(r.s62a.personal_effort_income, 1)
            assert w.s62a.profitability <= allowed + 1e-9, (seed, i)


def test_fuzz_documents():
    rng = random.Random(99)
    for i in range(60):
        r = compute(rnd_client(rng, i))
        render_html(build_accountant_doc(r, {"status": "בשיחה", "note": "x"}))
        render_html(build_client_doc(r, "משרד", "רו\"ח"))
