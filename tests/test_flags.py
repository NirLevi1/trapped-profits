"""בדיקות לדגלים של הנקודות הפתוחות – התנהגות שהאקסל לא מכסה."""

from __future__ import annotations

from pathlib import Path

from trapped_profits import compute, Flags
from trapped_profits.excel_io import load_client_from_excel

BASE_XLSX = Path(__file__).parent.parent / "golden" / "logic_v1.xlsx"


def _base(**flag_overrides):
    return load_client_from_excel(BASE_XLSX, flags=Flags(**flag_overrides))


# --- נקודה 2: בסיס מבחן ה-50% ---------------------------------------------------
def test_50pct_base_without_transition_deduction_is_stricter():
    """כשיש הגנת מעבר, האקסל מוריד את בסיס ה-50%; ברירת המחדל (הסיכום) לא."""
    strict = _base(deduct_transition_from_50pct_base=False)
    lenient = _base(deduct_transition_from_50pct_base=True)
    for ci in (strict, lenient):
        ci.distributions.dividend_in_determining_period = 5_760_000  # 80% → מוגן
        ci.distributions.determining_period_paid_and_taxed = True
    rs, rl = compute(strict), compute(lenient)
    assert rs.calc81.transition_reduction == rl.calc81.transition_reduction == 3_200_000
    # בסיס 3.9M: בלי הפחתה → 1.95M; עם הפחתה → 0.5×(3.9M−3.2M) = 0.35M
    assert rs.simulator.option_50pct == 1_950_000
    assert rl.simulator.option_50pct == 350_000
    # ללא הגנת מעבר אין הבדל בין הדגלים
    plain_s, plain_l = compute(_base(deduct_transition_from_50pct_base=False)), \
        compute(_base(deduct_transition_from_50pct_base=True))
    assert plain_s.simulator.option_50pct == plain_l.simulator.option_50pct


# --- נקודה 3: מסלול 20% ----------------------------------------------------------
def test_20pct_rule_can_be_disabled():
    on = _base(enable_20pct_current_year_rule=True)
    off = _base(enable_20pct_current_year_rule=False)
    for ci in (on, off):
        ci.distributions.dividends_taxed_current_year = 700_000  # ≥ 20% × 3.2M
    r_on, r_off = compute(on), compute(off)
    assert r_on.transition.rule_20pct_met is True
    assert r_on.calc81.transition_reduction == 3_200_000
    assert r_on.simulator.option_20pct_start_day == 640_000
    assert r_off.transition.rule_20pct_met is False
    assert r_off.calc81.transition_reduction == 0
    assert r_off.simulator.option_20pct_start_day is None


# --- נקודה 5: אומדן עודפים עדכני – תצוגה בלבד ----------------------------------
def test_updated_retained_estimate_is_display_only():
    without = compute(_base())
    ci = _base()
    ci.distributions.current_year_profit_estimate = 1_000_000
    with_est = compute(ci)
    # 7.8M + 1M×0.77 − 0 = 8.57M
    assert with_est.simulator.estimated_retained_year_end == 8_570_000
    assert without.simulator.estimated_retained_year_end is None
    # לא משפיע על המבחנים
    assert with_est.calc81 == without.calc81
    assert with_est.simulator.min_dividend == without.simulator.min_dividend


# --- תיקון באקסל: תרחיש ב׳ מסומן כאומדן ---------------------------------------
def test_estimate_flag_adds_manual_review_note():
    ci = _base()
    ci.is_estimate = True
    res = compute(ci)
    assert any("תרחיש ב" in m for m in res.manual_review)


def test_json_roundtrip():
    from trapped_profits.models import ClientInput
    ci = _base()
    again = ClientInput.from_dict(ci.to_dict())
    assert compute(again).to_dict() == compute(ci).to_dict()
