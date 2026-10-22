"""מנוע החישוב – תרגום הנוסחאות מהאקסל.

סדר החישוב (נגזר מתלויות הנוסחאות):
    רווחים נצברים (בסיס) → 62א → מגנים → רווחים חייבים → 81 → סימולטור → דאשבורד
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from typing import Any, Literal

from .models import ClientInput, Flags


# ---------------------------------------------------------------------------
# תוצאות ביניים – מבנה אחד לכל לשונית
# ---------------------------------------------------------------------------
@dataclass
class RetainedResult:
    formula_profits: float            # B11 – רווחים נצברים לפי הנוסחה המיסויית
    accounting_cap: float             # B17 – התקרה החשבונאית
    used_balance_sheet: bool          # True אם B5 ריק → נלקח מהמאזן
    retained_profits: float           # B19 – הנמוך מבין הנוסחה לתקרה
    retained_for_81a: float           # B21 – בסיס מבחן 6% ומבחן ההפסדים
    exempt_sources_total: float       # B28
    special_assets_net: float         # B29 (= מגנים!B31)
    exempt_alt1: float                # B30
    exempt_alt2: float                # B33
    taxable_retained_alt1: float      # B37
    taxable_retained_alt2: float      # B38
    manual_review_reasons: list[str]
    rollover_note: str = ""           # תרחיש ב׳: איך גולגלו העודפים = field(default_factory=list)
    roll_steps: list = field(default_factory=list)   # 22.10: שלבי הגלגול לתצוגה בלחיצה
    roll_base_year: int | None = None


@dataclass
class ShieldsResult:
    fixed_shield: float               # B7
    salary_added_to_expenses: float   # השכר שנוסף להוצאות (0 אם לא סומן)
    expenses_current_adjusted: float  # B10 + שכר
    expenses_avg_3y: float            # B13
    expenses_shield: float            # B14
    special_assets_gross: float       # B25
    special_assets_net: float         # B31
    assets_shield: float              # B36
    governing_shield_alt1: float      # B39 – ללא מגן נכסים
    governing_shield_alt2: float      # B40 – כולל מגן נכסים


@dataclass
class TransitionResult:
    start_day_remaining: float        # B14 – רווחים שנותרו מרווחי יום התחילה
    rule_20pct_met: bool              # B15
    determining_period_rate: float    # B21
    protected_until_year: int         # B22 – 0 = אין הגנה
    protected_in_tax_year: bool       # B23


@dataclass
class Section62AResult:
    other_income_total: float         # B12
    personal_effort_income: float     # B13
    taxable_income_personal_effort: float  # B16 (קלט, מוחזר לדוח)
    profitability: float              # B18
    governing_profitability: float    # B20
    crossed_25pct: bool               # B21
    revenue_threshold: float          # B24 – 30 מ' × בעלי שליטה
    below_revenue_threshold: bool     # B25
    exemption_750k_applies: bool      # B26 – פטור 62א(א1)(2)(ג)
    section_applies: bool             # B27
    deduction_25pct: float            # B30
    attributed_income: float          # B31 – = שכר לתיקון עד 31.12
    extra_tax_cost: float             # B34
    partnership_under_10pct: bool     # B39
    intercompany_dividend_attributed: float  # B42
    # אברהם 14.10 (10): איך חושבה עלות המס הנוספת
    extra_tax_cost_method: str = ""   # "מדרגות מס על שכר X" / "מס שולי משוקלל N%"
    owner_salary: float | None = None
    # אברהם 14.10 (12): ריכוזיות – חלקו של הלקוח הגדול ביותר מסך ההכנסות (0 = אין נתון)
    concentration_share: float = 0.0
    concentration_top_name: str = ""
    concentration_share_prev_year: float = 0.0   # אותו לקוח בכרטסת השנה הקודמת (0 = אין נתון)
    # מה קורה אם מבחן הריכוזיות מתקיים (22 מתוך 36 חודשים): ייחוס מלא – לא רק מעל 25%, גם עם פטור 750 אלף
    attributed_if_concentration: float = 0.0
    extra_tax_if_concentration: float = 0.0
    customers_breakdown: list = field(default_factory=list)   # [{"name","amount","share"}] + "אחרים"
    # אברהם (סבב 2, 3): 70% מלקוח אחד על סך 36 חודשים (שלוש כרטסות)
    concentration_share_36m: float = 0.0
    concentration_years: list = field(default_factory=list)   # השנים שנכנסו לחישוב
    concentration_met_by_data: bool = False                    # שלוש שנים ו-≥70% → המבחן מתקיים לפי הנתונים
    concentration_test_met: bool = False                       # ידני או לפי הנתונים


@dataclass
class Calc81Result:
    transition_reduction: float       # B4
    excess_alt1: float                # B5
    excess_alt2: float                # B6
    chosen_alternative: Literal[1, 2] # B7
    taxable_retained: float           # B8
    governing_shield: float           # B9
    excess_profits: float             # B10
    dividend_deducted: float          # B13
    surtax_base: float                # B14
    required_distribution_rate: float # B17 – 5% ב-2025, 6% מ-2026
    exempt_losses: bool               # B18
    exempt_50pct: bool                # B19
    exempt_6pct: bool                 # B20
    exempt_transition_2025: bool      # B21
    is_exempt: bool                   # B23
    surtax: float                     # B27
    # אברהם 14.10 (6): מצב אחד במילים – "פטור – <מבחן>" / "מוגן בהוראת מעבר עד שנה" / "חייב" / ...
    status_label: str = ""
    exempt_reason: str = ""
    # אברהם 14.10 (1): החלופה מוצגת רק כשיש רווחים ממקור פטור
    alternative_relevant: bool = False


@dataclass
class SimulatorResult:
    option_6pct: float                # B5
    option_50pct: float               # B6
    cheaper_option: str               # B7
    min_dividend: float               # B8
    already_distributed: float        # B9
    gap_to_close: float               # B10
    dividend_tax_cost: float          # B14
    surtax_if_not_distributing: float # B15
    difference: float                 # B16
    years_to_breakeven: float         # B17
    recommendation: str               # B20
    # תוספת למול האקסל: האם בכלל נדרשת פעולה במסלול 81 (החוק חל, אין פטור, יש תוספת מס).
    # באקסל "פער לסגירה" מוצג גם ללקוח מוגן/פטור – בדיוק הטעות שהסיכום מזהיר ממנה.
    action_required: bool = False
    # נקודה 3 – חלופת 20% מרווחי יום התחילה (מוצגת רק אם הדגל פעיל ויש רווחים שנותרו)
    option_20pct_start_day: float | None = None
    # נקודה 5 – אומדן עודפים לתום השנה (תצוגה בלבד)
    estimated_retained_year_end: float | None = None
    estimated_retained_parts: dict | None = None      # 21.10: פירוט האומדן – עודפים + רווח − מס − דיבידנד
    # החלטה 10 – אם משלמים את שכר התיקון של 62א עד 31.12: כמה תוספת המס של 81 יורדת (מגן ההוצאות גדל)
    surtax_if_salary_paid: float | None = None
    # החלטה 12 – המלצה מנוסחת (כמה משפטים עם מספרים), לכרטיס ולדוח
    recommendation_text: str = ""


@dataclass
class DashboardResult:
    status_81: str                    # B25
    status_62a: str                   # B26
    status_overall: str               # B27
    color_81: Literal["ירוק", "צהוב", "אדום"]
    color_62a: Literal["ירוק", "צהוב", "אדום"]
    color_overall: Literal["ירוק", "צהוב", "אדום"]
    protected_until: str              # B16


@dataclass
class ClientResult:
    name: str
    tax_year: int
    previous_year: int
    data_as_of: str
    is_estimate: bool
    logic_version: str
    flags: Flags
    applies_81: bool                  # מבנה!B13
    applies_62a: bool                 # מבנה!B14
    companies_for_750k_split: int     # מבנה!B20
    retained: RetainedResult
    s62a: Section62AResult
    shields: ShieldsResult
    transition: TransitionResult
    calc81: Calc81Result
    simulator: SimulatorResult
    dashboard: DashboardResult
    manual_review: list[str]
    missing_fields: list[str] = field(default_factory=list)   # החלטה 5 – שדות קריטיים שנשארו ריקים
    annualization_factor: float = 1.0                         # החלטה 4 – 12 ÷ חודשים (1.0 = שנה מלאה)
    next_year_notes: list[str] = field(default_factory=list)  # אברהם 14.10 (22) – תכנון לשנה הבאה
    # אברהם (סבב 2, 4, 5–7, 14, 15): מה בפועל ומה אומדן, ואילו אומדנים המערכת הוסיפה (לבדיקת אברהם)
    actuals: dict = field(default_factory=dict)               # {"through_month", "revenue", "taxable_income", "expenses"} לפני הכפלה
    estimate_notes: list[str] = field(default_factory=list)
    # סבב 3: כל פריט אומדן/תיקון – {key, label, month, amount, status: pending|accepted|corrected|dismissed, source}
    estimate_items: list = field(default_factory=list)
    data_breakdown: dict = field(default_factory=dict)      # {"file": …, "estimates": …, "corrections": …} – הוצאות השנה (לפני הכפלה)
    months_gap_table: dict = field(default_factory=dict)    # {סעיף: [12]} עם None בחודשים שאחרי הנתונים – לטבלת החוסרים
    years_used: dict = field(default_factory=dict)            # {"retained": "דוח 2025", "expenses_avg": "2024–2026", "concentration": "2024–2026"}
    scenario_label: str = ""                                  # "" / "אומדן (תרחיש ב׳)" / "אומדן (תרחיש ג׳ – גלגול שנתיים)"
    months_table: dict | None = None                          # סבב 4: מאזן הבוחן המלא – כל שורה × 12 חודשים (קובץ / אומדן / תיקון) – כשיש tb_rows

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# לשונית «רווחים_נצברים» – חלק א-ב (בסיס). חלקים ג-ה אחרי המגנים.
# ---------------------------------------------------------------------------
def _roll_lag(ci: ClientInput) -> int:
    """כמה שנים צריך לגלגל מהעודפים שבטופס לתום השנה הקודמת: 0 רגיל, 1 תרחיש ב׳, 2 תרחיש ג׳ (דוח ישן בשנתיים)."""
    st = ci.structure
    base = ci.retained.retained_as_of_year or st.last_closed_report_year
    if not base:
        return 0
    return max(0, min(2, st.previous_year - int(base)))


def scenario_label(ci: ClientInput) -> str:
    lag = _roll_lag(ci)
    if lag >= 2:
        return "אומדן (תרחיש ג׳ – גלגול שנתיים)"
    if lag == 1 or ci.structure.is_scenario_b or ci.is_estimate:
        return "אומדן (תרחיש ב׳)"
    return ""


def _roll_steps(ci: ClientInput) -> list[dict]:
    """שלבי הגלגול: [{"year", "from", "profit", "after_tax", "dividend", "to"}]. שנה בלי רווח לגלגול – עוצר שם."""
    r, d, t = ci.retained, ci.distributions, ci.s62a.corporate_tax_rate
    lag = _roll_lag(ci)
    steps = []
    cur = r.balance_sheet_retained_earnings
    plan = []
    if lag >= 2:
        plan.append((ci.structure.previous_year - 1, r.prev2_year_profit_for_rollover, d.dividends_prev2_year))
    if lag >= 1:
        plan.append((ci.structure.previous_year, r.prev_year_profit_for_rollover, d.dividends_prev_year))
    for year, p, div in plan:
        if p is None:
            break
        after_tax = p * (1 - t) if p > 0 else p
        nxt = cur + after_tax - div
        steps.append({"year": year, "from": cur, "profit": p, "after_tax": after_tax, "dividend": div, "to": nxt})
        cur = nxt
    return steps


def _rolled_retained(ci: ClientInput) -> float:
    """תרחיש ב׳/ג׳: הדוח הסגור ישן → עודפים לתום השנה הקודמת = עודפי הדוח + רווח כל שנה פתוחה × (1 − מס חברות) − הדיבידנד שלה.
    בלי רווח לגלגול – העודפים כמו שהוזנו (אומדן ידני של אברהם)."""
    steps = _roll_steps(ci)
    return steps[-1]["to"] if steps else ci.retained.balance_sheet_retained_earnings


def _rolled_start_day(ci: ClientInput) -> float | None:
    """תרחיש ג׳: עודפים לתום 2024 (= רווחי יום התחילה) אינם בדוח – אומדן מהשלב הראשון של הגלגול."""
    if _roll_lag(ci) < 2:
        return None
    steps = [x for x in _roll_steps(ci) if x["year"] == 2024]
    return steps[0]["to"] if steps else None


def _rollover_note(ci: ClientInput) -> str:
    steps = _roll_steps(ci)
    if not steps:
        return ""
    t = ci.s62a.corporate_tax_rate
    base = ci.retained.retained_as_of_year or ci.structure.last_closed_report_year
    parts = [f"גלגול ({'תרחיש ג׳' if _roll_lag(ci) >= 2 else 'תרחיש ב׳'}): עודפי {'הדוח הסגור ' if not ci.retained.retained_as_of_year else ''}{base} {steps[0]['from']:,.0f}"]
    for x in steps:
        parts.append(f"+ רווח {x['year']} {x['profit']:,.0f} × (1 − {t:.0%}) = {x['after_tax']:,.0f} − דיבידנד {x['year']} {x['dividend']:,.0f} → עודפי {x['year']} {x['to']:,.0f}")
    return " ".join(parts)


def _retained_base(ci: ClientInput) -> tuple[float, float, bool, float, float]:
    r = ci.retained
    formula = (r.cumulative_taxable_income or 0.0) + r.cumulative_exempt_income \
        + r.cumulative_land_appreciation - r.cumulative_tax - r.cumulative_dividends \
        - r.uncredited_loss                                                   # B11
    cap = _rolled_retained(ci) + r.capitalized_profits \
        + r.transparent_entity_profits                                        # B17
    used_bs = not r.cumulative_taxable_income                                 # B19: IF(OR(B5="",B5=0),…)
    retained = cap if used_bs else min(formula, cap)                          # B19
    for_81a = max(0.0, retained - r.attributed_to_shareholders)               # B21
    return formula, cap, used_bs, retained, for_81a


def _retained_full(ci: ClientInput, special_assets_net: float) -> RetainedResult:
    r = ci.retained
    formula, cap, used_bs, retained, for_81a = _retained_base(ci)
    exempt_total = r.exempt_preferred_enterprise_income + r.exempt_industrial_sales_income \
        + r.exempt_building_8a_income + r.exempt_financial_institution_income  # B28
    alt1 = max(0.0, exempt_total - special_assets_net)                        # B30
    alt2 = r.exempt_profits_last_7_years                                      # B33
    reasons: list[str] = []
    # יתרת העודפים במאזן היא הבסיס של הפיילוט (החלטת 13.10) – לא סיבה לבדיקה ידנית.
    # הנתון נשמר ב-used_balance_sheet לדוח; לבדיקה ידנית רק כשהוזנו נתוני מס והנוסחה נמוכה מהמאזן.
    if not used_bs and formula < cap:
        reasons.append("רווחים נצברים לפי הנוסחה המיסויית נמוכים מיתרת העודפים במאזן – לאמת את נתוני המס המצטברים")
    return RetainedResult(
        formula_profits=formula,
        accounting_cap=cap,
        used_balance_sheet=used_bs,
        retained_profits=retained,
        retained_for_81a=for_81a,
        exempt_sources_total=exempt_total,
        special_assets_net=special_assets_net,
        exempt_alt1=alt1,
        exempt_alt2=alt2,
        taxable_retained_alt1=max(0.0, for_81a - alt1),                       # B37
        taxable_retained_alt2=max(0.0, for_81a - alt2),                       # B38
        manual_review_reasons=reasons,
        rollover_note=_rollover_note(ci),
        roll_steps=[{k: (round(v) if isinstance(v, float) else v) for k, v in x.items()} for x in _roll_steps(ci)],
        roll_base_year=(ci.retained.retained_as_of_year or ci.structure.last_closed_report_year) if _roll_steps(ci) else None,
    )


# ---------------------------------------------------------------------------
# לשונית «סעיף_62א»
# ---------------------------------------------------------------------------
def _conc_met_by_data(ci: ClientInput) -> bool:
    """אברהם (סבב 2, 3): שלוש כרטסות (36 חודשים) והלקוח הגדול של השנה מעל 70% מסך שלוש השנים."""
    s = ci.s62a
    cur = [(str(c.get("name") or ""), float(c.get("amount") or 0)) for c in (s.top_customers or []) if float(c.get("amount") or 0) > 0]
    if not cur:
        return False
    cur.sort(key=lambda x: -x[1])
    name = cur[0][0]
    num = cur[0][1]
    den = max(s.total_revenue, sum(a for _, a in cur))
    n_years = 1
    for lst, tot_in in ((s.top_customers_prev_year, s.prev_year_revenue_for_concentration), (s.top_customers_prev2_year, s.prev2_year_revenue_for_concentration)):
        rows = [(str(c.get("name") or ""), float(c.get("amount") or 0)) for c in (lst or []) if float(c.get("amount") or 0) > 0]
        if rows:
            num += next((a for n, a in rows if n == name), 0.0)
            den += max(tot_in, sum(a for _, a in rows))
            n_years += 1
    return n_years >= 3 and den > 0 and num / den >= 0.70 - 1e-9


def _section_62a(ci: ClientInput, retained_for_81a: float) -> Section62AResult:
    s, st = ci.s62a, ci.structure
    other = s.other_interest + s.other_dividend + s.other_rent + s.other_asset_sale \
        + s.other_securities_inventory_sale + s.other_real_estate_sale \
        + s.other_misc_income                                                   # B12 (+ הכנסות אחרות ממאזן הבוחן – 15.10)
    personal = max(0.0, s.total_revenue - other)                                # B13
    profitability = (s.taxable_income_personal_effort + s.related_company_payments) / personal \
        if personal else 0.0                                                    # B18 (IFERROR → 0)
    if st.tax_year == 2025 and s.avg_profitability_2023_2025 > 0:               # B20
        governing = min(profitability, s.avg_profitability_2023_2025)
    else:
        governing = profitability
    crossed = governing > 0.25 + 1e-9                                           # B21 – "עולה על 25%"; 25.0% בדיוק (אחרי שכר תיקון) אינו חצייה
    threshold = 30_000_000.0 * max(1, st.controlling_owners_count)              # B24
    below = personal < threshold                                                # B25
    exemption_750k = (not st.owner_controls_another_company) and retained_for_81a <= 750_000  # B26
    applies = st.applies_62a and crossed and below and not exemption_750k       # B27
    if ci.flags.deduction_base_excludes_related_payments:                       # B30 – נקודה 6
        deduction = 0.25 * max(0.0, personal - s.related_company_payments)      #   האקסל
    else:
        deduction = 0.25 * personal                                             #   הסיכום
    if not st.applies_62a:                                                      # B31
        attributed = 0.0
    elif s.concentration_test_met or _conc_met_by_data(ci):
        attributed = s.taxable_income_personal_effort                           # חסם עליון – ייחוס מלא
    elif applies:
        attributed = max(0.0, s.taxable_income_personal_effort - deduction)
    else:
        attributed = 0.0
    # B34 – אברהם 14.10 (10): עם שכר בעלים – לפי מדרגות מס; בלעדיו – מס שולי משוקלל (כמו באקסל)
    if attributed <= 0:
        extra_cost, method = 0.0, "אין הכנסה מיוחסת – אין עלות נוספת"
    elif s.owner_salary_current_year is not None:
        sal = max(0.0, s.owner_salary_current_year)
        extra_cost = max(0.0, _individual_tax(sal + attributed) - _individual_tax(sal) - s.corporate_tax_rate * attributed)
        method = f"מדרגות מס על שכר {sal:,.0f} ₪ + הכנסה מיוחסת, בניכוי מס חברות {s.corporate_tax_rate:.0%}"
    else:
        extra_cost = max(0.0, attributed * (s.marginal_tax_rate - s.corporate_tax_rate))
        method = f"מס שולי משוקלל {s.marginal_tax_rate:.0%} פחות מס חברות {s.corporate_tax_rate:.0%} (לא הוזן שכר בעלים)"
    # אברהם 14.10 (12): ריכוזיות לפי הלקוחות הגדולים
    customers = [(str(c.get("name") or "ללא שם"), float(c.get("amount") or 0)) for c in (s.top_customers or [])
                 if float(c.get("amount") or 0) > 0]
    customers.sort(key=lambda x: -x[1])
    base_rev = max(s.total_revenue, sum(a for _, a in customers))
    breakdown = [{"name": n, "amount": a, "share": a / base_rev} for n, a in customers] if base_rev > 0 else []
    if breakdown:
        rest = base_rev - sum(a for _, a in customers)
        if rest > 0.5:
            breakdown.append({"name": "אחרים", "amount": rest, "share": rest / base_rev})
    conc_share = breakdown[0]["share"] if customers and base_rev > 0 else 0.0
    conc_name = customers[0][0] if customers else ""
    # שנה קודמת (כרטסת קודמת) – אותו לקוח גדול גם שם?
    prev = [(str(c.get("name") or ""), float(c.get("amount") or 0)) for c in (s.top_customers_prev_year or []) if float(c.get("amount") or 0) > 0]
    prev_share = 0.0
    if prev and conc_name:
        tot_prev = max(s.prev_year_revenue_for_concentration, sum(a for _, a in prev))
        same = next((a for n, a in prev if n == conc_name), 0.0)
        prev_share = same / tot_prev if tot_prev > 0 else 0.0
    # 36 חודשים: סך הלקוח הגדול (של השנה) בשלוש הכרטסות ÷ סך שלוש הכרטסות
    years_avail = [st.tax_year] if customers else []
    num36, den36 = (next((a for n, a in customers if n == conc_name), 0.0), base_rev) if customers and base_rev > 0 else (0.0, 0.0)
    for lst, tot_in, y in ((prev, s.prev_year_revenue_for_concentration, st.tax_year - 1),
                           ([(str(c.get("name") or ""), float(c.get("amount") or 0)) for c in (s.top_customers_prev2_year or []) if float(c.get("amount") or 0) > 0],
                            s.prev2_year_revenue_for_concentration, st.tax_year - 2)):
        if lst:
            tot = max(tot_in, sum(a for _, a in lst))
            num36 += next((a for n, a in lst if n == conc_name), 0.0)
            den36 += tot
            years_avail.append(y)
    share36 = num36 / den36 if den36 > 0 else 0.0
    met_by_data = len(years_avail) >= 3 and share36 >= 0.70 - 1e-9
    conc_met = s.concentration_test_met or met_by_data
    full = s.taxable_income_personal_effort if st.applies_62a else 0.0
    if full > 0 and s.owner_salary_current_year is not None:
        sal = max(0.0, s.owner_salary_current_year)
        full_cost = max(0.0, _individual_tax(sal + full) - _individual_tax(sal) - s.corporate_tax_rate * full)
    else:
        full_cost = max(0.0, full * (s.marginal_tax_rate - s.corporate_tax_rate))
    partnership_under = 0 < st.partnership_income_share < 0.10                  # B39
    rate = s.holding_rate_in_paying_company                                     # B42
    interco = 0.55 * s.intercompany_dividend_received \
        if (rate is not None and rate < 0.10) else 0.0
    return Section62AResult(
        other_income_total=other,
        personal_effort_income=personal,
        taxable_income_personal_effort=s.taxable_income_personal_effort,
        profitability=profitability,
        governing_profitability=governing,
        crossed_25pct=crossed,
        revenue_threshold=threshold,
        below_revenue_threshold=below,
        exemption_750k_applies=exemption_750k,
        section_applies=applies,
        deduction_25pct=deduction,
        attributed_income=attributed,
        extra_tax_cost=extra_cost,
        partnership_under_10pct=partnership_under,
        intercompany_dividend_attributed=interco,
        extra_tax_cost_method=method,
        owner_salary=s.owner_salary_current_year,
        concentration_share=conc_share,
        concentration_top_name=conc_name,
        concentration_share_prev_year=prev_share,
        attributed_if_concentration=full,
        extra_tax_if_concentration=full_cost,
        customers_breakdown=breakdown,
        concentration_share_36m=share36,
        concentration_years=sorted(years_avail),
        concentration_met_by_data=met_by_data,
        concentration_test_met=conc_met,
    )


# מדרגות מס הכנסה ליחיד, שנתי, 2025 (מוקפאות עד 2027 לפי חוק ההסדרים). ללא ביטוח לאומי ונקודות זיכוי –
# לאברהם: האם לכלול? (שאלה פתוחה). מעל 721,560 – 47% + מס יסף 3%.
TAX_BRACKETS_2025 = [(84_120, 0.10), (120_720, 0.14), (193_800, 0.20), (269_280, 0.31),
                     (560_280, 0.35), (721_560, 0.47), (float("inf"), 0.50)]


def _individual_tax(income: float) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in TAX_BRACKETS_2025:
        if income <= lower:
            break
        tax += (min(income, upper) - lower) * rate
        lower = upper
    return tax


# ---------------------------------------------------------------------------
# לשונית «מגנים»
# ---------------------------------------------------------------------------
def _shields(ci: ClientInput, attributed_income_62a: float) -> ShieldsResult:
    sh, st = ci.shields, ci.structure
    fixed = sh.fixed_shield_base / st.companies_for_750k_split                  # B7
    salary_add = attributed_income_62a if sh.pay_62a_salary_by_year_end else 0.0  # B13/B14 IF(B15="כן",…)
    cur = sh.expenses_current_year + salary_add
    avg3 = (cur + sh.expenses_prev_year + sh.expenses_prev2_year) / 3.0          # B13
    exp_shield = max(cur, avg3)                                                  # B14
    gross = sh.special_securities + sh.special_financial_asset + sh.special_intangible_royalty \
        + sh.special_real_estate + sh.special_loans_deposits_cash                # B25
    excl = sh.excl_own_use_real_estate + sh.excl_rental_building \
        + sh.excl_pledged_cash_financing + sh.excl_regulatory_equity_cash
    net = max(0.0, gross - excl)                                                 # B31
    assets_shield = max(0.0, sh.total_assets_cost - net - sh.share_capital_and_premium
                        - sh.related_party_loan + sh.held_company_cost)          # B36
    return ShieldsResult(
        fixed_shield=fixed,
        salary_added_to_expenses=salary_add,
        expenses_current_adjusted=cur,
        expenses_avg_3y=avg3,
        expenses_shield=exp_shield,
        special_assets_gross=gross,
        special_assets_net=net,
        assets_shield=assets_shield,
        governing_shield_alt1=max(fixed, exp_shield),                            # B39
        governing_shield_alt2=max(fixed, exp_shield, assets_shield),             # B40
    )


# ---------------------------------------------------------------------------
# לשונית «חלוקות» – חלקים ג-ד (הוראות מעבר)
# ---------------------------------------------------------------------------
def _transition(ci: ClientInput) -> TransitionResult:
    d, st, f = ci.distributions, ci.structure, ci.flags
    remaining = max(0.0, d.start_day_excess_profits - d.start_day_dividends_taxed)  # B14
    rule20 = f.enable_20pct_current_year_rule and remaining > 0 \
        and d.dividends_taxed_current_year >= 0.2 * remaining                        # B15
    start_ret = d.retained_at_start_day or (_rolled_start_day(ci) or 0.0)        # תרחיש ג׳: עודפי 2024 מהגלגול (אומדן)
    rate = d.dividend_in_determining_period / start_ret \
        if start_ret else 0.0                                                        # B21
    if not d.determining_period_paid_and_taxed:                                      # B22
        until = 0
    elif rate >= 0.90:
        until = 2029
    elif rate >= 0.75:
        until = 2028
    elif rate >= 0.60:
        until = 2027
    elif rate >= 0.35:
        until = 2026
    else:
        until = 0
    protected = until > 0 and 2026 <= st.tax_year <= until                           # B23
    return TransitionResult(
        start_day_remaining=remaining,
        rule_20pct_met=rule20,
        determining_period_rate=rate,
        protected_until_year=until,
        protected_in_tax_year=protected,
    )


# ---------------------------------------------------------------------------
# לשונית «חישוב_81»
# ---------------------------------------------------------------------------
def _calc81(ci: ClientInput, ret: RetainedResult, sh: ShieldsResult, tr: TransitionResult) -> Calc81Result:
    d, st, f, sim = ci.distributions, ci.structure, ci.flags, ci.simulator
    reduction = tr.start_day_remaining if (tr.rule_20pct_met or tr.protected_in_tax_year) else 0.0  # B4
    alt1 = max(0.0, ret.taxable_retained_alt1 - sh.governing_shield_alt1 - reduction)  # B5
    alt2 = max(0.0, ret.taxable_retained_alt2 - sh.governing_shield_alt2 - reduction)  # B6
    # B7 – באקסל: IF(B5<=B6,"חלופה 1","חלופה 2"). סטייה מכוונת (סיכום, 81 שלב 4):
    # "לחברה בלי רווחים ממקור פטור – תמיד תרחיש (2)", ובשוויון אין סיבה לוותר על מגן הנכסים.
    if ret.exempt_sources_total <= 0 and ret.exempt_alt2 <= 0:
        chosen: Literal[1, 2] = 2
    else:
        chosen = 1 if alt1 < alt2 else 2
    taxable = ret.taxable_retained_alt1 if chosen == 1 else ret.taxable_retained_alt2  # B8
    shield = sh.governing_shield_alt1 if chosen == 1 else sh.governing_shield_alt2     # B9
    excess = min(alt1, alt2)                                                           # B10
    div = d.dividends_taxed_current_year                                               # B13
    base = max(0.0, excess - div)                                                      # B14
    rate = 0.05 if st.tax_year <= 2025 else 0.06                                       # B17
    ex_losses = ret.retained_for_81a > 0 and d.losses_current_year > 0.1 * ret.retained_for_81a  # B18
    base_50 = _base_50pct(ci, reduction)
    # B19 – באקסל התנאי הוא B9>0; כאן נדרש בסיס חיובי אחרי ההפחתה, אחרת דיבידנד 0 "עומד" במבחן
    ex_50 = base_50 > 0 and div >= 0.5 * base_50
    ex_6 = ret.retained_for_81a > 0 and div >= rate * ret.retained_for_81a             # B20
    ex_tr25 = st.tax_year == 2025 and d.determining_period_paid_and_taxed \
        and tr.determining_period_rate >= 0.05                                         # B21
    is_exempt = ex_losses or ex_50 or ex_6 or ex_tr25                                  # B23
    surtax = 0.0 if (not st.applies_81 or is_exempt) else sim.surtax_rate * base       # B27
    # אברהם 14.10 (6): תווית מצב אחת
    reasons = []
    if ex_losses:
        reasons.append("הפסדי השנה מעל 10% מהרווחים הנצברים")
    if ex_50:
        reasons.append("חולקו 50% מהרווחים העודפים")
    if ex_6:
        reasons.append(f"חולקו {rate:.0%} מהרווחים הנצברים")
    if ex_tr25:
        reasons.append("חלוקה בתקופה הקובעת 2025")
    exempt_reason = "; ".join(reasons)
    if not st.applies_81:
        label = "החוק אינו חל"
    elif is_exempt:
        label = "פטור – " + exempt_reason
    elif tr.protected_in_tax_year and excess <= 0:
        label = f"מוגן בהוראת מעבר עד {tr.protected_until_year}"
    elif excess <= 0:
        label = "אין רווחים עודפים – המגן מכסה"
    elif base <= 0:
        label = "אין בסיס לתוספת מס אחרי הדיבידנד שחולק"
    else:
        label = "חייב בתוספת מס"
    return Calc81Result(
        status_label=label, exempt_reason=exempt_reason,
        alternative_relevant=ret.exempt_sources_total > 0 or ret.exempt_alt2 > 0,
        transition_reduction=reduction,
        excess_alt1=alt1,
        excess_alt2=alt2,
        chosen_alternative=chosen,
        taxable_retained=taxable,
        governing_shield=shield,
        excess_profits=excess,
        dividend_deducted=div,
        surtax_base=base,
        required_distribution_rate=rate,
        exempt_losses=ex_losses,
        exempt_50pct=ex_50,
        exempt_6pct=ex_6,
        exempt_transition_2025=ex_tr25,
        is_exempt=is_exempt,
        surtax=surtax,
    )


def _base_50pct(ci: ClientInput, reduction: float) -> float:
    """בסיס מבחן ה-50% – נקודה פתוחה 2.

    האקסל: MAX(0, חלוקות!B9 - חישוב_81!B4).  הסיכום: חלוקות!B9 בלבד.
    """
    b9 = ci.distributions.excess_profits_prev_year
    if ci.flags.deduct_transition_from_50pct_base:
        return max(0.0, b9 - reduction)
    return max(0.0, b9)


# ---------------------------------------------------------------------------
# לשונית «סימולטור»
# ---------------------------------------------------------------------------
def _simulator(ci: ClientInput, ret: RetainedResult, tr: TransitionResult, c81: Calc81Result) -> SimulatorResult:
    d, st, sim, f = ci.distributions, ci.structure, ci.simulator, ci.flags
    opt6 = c81.required_distribution_rate * ret.retained_for_81a                  # B5
    base_50 = _base_50pct(ci, c81.transition_reduction)
    opt50 = 0.5 * base_50                                                          # B6
    # B7/B8 – באקסל MIN(B5,B6) גם כש-B6=0 (אין נתון שנה קודמת) → "דיבידנד מינימלי 0". כאן חלופת
    # 50% נכנסת להשוואה רק כשיש לה בסיס חיובי (עקבי עם מבחן הפטור, חישוב_81!B19).
    if base_50 > 0 and opt50 < opt6:
        cheaper, min_div = "חלופת 50%", opt50
    else:
        cheaper, min_div = "חלופת 6%", opt6
    already = d.dividends_taxed_current_year                                       # B9
    gap = max(0.0, min_div - already)                                              # B10
    div_tax = gap * sim.dividend_tax_rate                                          # B14
    surtax = c81.surtax                                                            # B15
    diff = div_tax - surtax                                                        # B16
    years = 0.0 if surtax <= 0 else div_tax / surtax                               # B17

    # B20 – עם שלושה תיקונים לעומת האקסל (ראו README, "באגים ידועים באקסל"):
    #   1. מבנה!B9 (תא ריק) → מבנה!B13 (חלה מערכת 81)
    #   2. חישוב_81!B19="כן" (התא מחזיר "פטור"/"לא", לעולם לא "כן") → חישוב_81!B23 (האם קיים פטור)
    #   3. B10<B11 (B11 ריק; וגם משווה דיבידנד ברוטו למס) → B14<B15 (מס דיבידנד מול תוספת המס)
    #   וכן "אין רווחים עודפים" נבדק על רווחי השנה (חישוב_81!B10) ולא על בסיס ה-50% של שנה קודמת.
    if not st.applies_81:
        rec = "החוק אינו חל – אין פעולה נדרשת"
    elif c81.is_exempt:
        rec = "עומדת בפטור – אין פעולה נדרשת"
    elif c81.excess_profits <= 0:
        rec = "אין רווחים עודפים חייבים – אין פעולה נדרשת"
    elif div_tax < surtax:
        rec = "מומלץ לשקול חלוקה – זולה מתוספת המס באותה שנה"
    else:
        rec = "תוספת המס זולה יותר השנה – יש לבחון את ההשפעה הרב-שנתית"

    opt20 = None
    if f.enable_20pct_current_year_rule and tr.start_day_remaining > 0:
        opt20 = 0.2 * tr.start_day_remaining

    est = None
    est_parts = None
    if d.current_year_profit_estimate is not None:
        p = d.current_year_profit_estimate
        after_tax = p * (1 - ci.s62a.corporate_tax_rate) if p > 0 else p   # על הפסד אין מס
        # 21.10 (אברהם): בסיס = עודפים לתום השנה הקודמת (בתרחיש ב׳/ג׳ – אחרי הגלגול), ופירוט לתצוגה
        base = _rolled_retained(ci) if _roll_lag(ci) else ci.retained.balance_sheet_retained_earnings
        est = base + after_tax - d.dividends_taxed_current_year
        est_parts = {"base": round(base), "base_year": st.previous_year, "rolled": bool(_roll_lag(ci)), "profit": round(p),
                     "tax": round(p - after_tax), "tax_rate": ci.s62a.corporate_tax_rate, "dividend": round(d.dividends_taxed_current_year)}

    return SimulatorResult(
        option_6pct=opt6, option_50pct=opt50, cheaper_option=cheaper, min_dividend=min_div,
        already_distributed=already, gap_to_close=gap, dividend_tax_cost=div_tax,
        surtax_if_not_distributing=surtax, difference=diff, years_to_breakeven=years,
        recommendation=rec, action_required=c81.surtax > 0,
        option_20pct_start_day=opt20, estimated_retained_year_end=est, estimated_retained_parts=est_parts,
    )


# ---------------------------------------------------------------------------
# לשונית «דאשבורד»
# ---------------------------------------------------------------------------
def _dashboard(ci: ClientInput, s62: Section62AResult, tr: TransitionResult,
               c81: Calc81Result, sim: SimulatorResult, missing: list[str] | None = None) -> DashboardResult:
    st, f = ci.structure, ci.flags
    # B25
    if tr.protected_in_tax_year:
        status81 = "אדום – חשוף לתוספת מס" if c81.surtax > 0 \
            else f"ירוק – מוגן לפי הוראת מעבר עד {tr.protected_until_year}"
    elif not st.applies_81:
        status81 = "ירוק – החוק אינו חל"
    elif c81.surtax > 0:
        status81 = "אדום – חשוף לתוספת מס"
    elif c81.excess_profits > 0 and sim.gap_to_close > 0 and not c81.is_exempt:
        # באקסל אין את "ולא פטור": לקוח פטור לפי מבחן ההפסדים היה מקבל "נדרשת חלוקה"
        status81 = "צהוב – נדרשת חלוקה לשמירת הפטור"
    else:
        status81 = "ירוק – מוגן"
    # B26
    if not st.applies_62a:
        status62 = "ירוק – הסעיף אינו חל"
    elif s62.concentration_test_met:
        status62 = "אדום – מבחן ריכוזיות: ייחוס מלא" + (f" (לפי כרטסות {s62.concentration_years[0]}–{s62.concentration_years[-1]}: {s62.concentration_share_36m:.0%})" if s62.concentration_met_by_data and not ci.s62a.concentration_test_met else "")
    elif s62.section_applies and s62.attributed_income > 0.5:
        status62 = "אדום – ייחוס הכנסה לבעל המניות"
    elif s62.concentration_share >= 0.70:
        status62 = f"צהוב – לקוח אחד {s62.concentration_share:.0%} מההכנסות – לבדוק ריכוזיות על 36 חודשים"
    elif s62.crossed_25pct and s62.exemption_750k_applies:
        # 17.10: רווחיות מעל 25% אבל עודפים עד 750 אלף ואין שליטה בחברה נוספת – הסעיף אינו חל (קודם: "מתקרבת לסף" – מטעה)
        # צבע כמו באקסל של אברהם (צהוב – לעקוב: כשהעודפים יעברו 750 אלף הסעיף יחול); רק הניסוח מדויק
        status62 = f"צהוב – פטור: עודפים עד 750 אלף ₪; רווחיות {s62.governing_profitability:.0%} מעל 25% – לעקוב"
    elif s62.crossed_25pct and not s62.below_revenue_threshold:
        status62 = "ירוק – מחזור מעל הסף – הסעיף אינו חל"
    elif s62.governing_profitability > f.profitability_warning_threshold:
        status62 = "צהוב – רווחיות מתקרבת לסף 25%"
    elif s62.concentration_share >= 0.55:
        status62 = f"צהוב – לקוח אחד {s62.concentration_share:.0%} מההכנסות – מתקרב ל-70%"
    else:
        status62 = "ירוק – מתחת לסף"
    c81c, c62c = status81.split(" ")[0], status62.split(" ")[0]
    # B27
    if "אדום" in (c81c, c62c):
        overall = "אדום – טיפול נדרש"
    elif "צהוב" in (c81c, c62c):
        overall = "צהוב – מעקב"
    elif missing:
        overall = "צהוב – חסרים נתונים"      # ירוק על בסיס אפסים אינו ירוק (החלטה 5)
    else:
        overall = "ירוק"
    return DashboardResult(
        status_81=status81, status_62a=status62, status_overall=overall,
        color_81=c81c, color_62a=c62c, color_overall=overall.split(" ")[0],
        protected_until=str(tr.protected_until_year) if tr.protected_in_tax_year else "אין",  # B16
    )


# ---------------------------------------------------------------------------
# סימונים לבדיקה ידנית (סיכום, "לבדיקה ידנית")
# ---------------------------------------------------------------------------
def _manual_review(ci: ClientInput, ret: RetainedResult, s62: Section62AResult, sh: ShieldsResult) -> list[str]:
    out = list(ret.manual_review_reasons)
    if ci.shields.special_securities > 0 or ci.shields.held_company_cost > 0:
        out.append("חברה עם ני\"ע או החזקות – העודפים החשבונאיים עלולים לנפח את הבסיס")
    if ci.s62a.other_interest > 0 or ci.s62a.other_rent > 0:
        out.append("הכנסות מריבית או שכירות – לוודא ייחוס הוצאות ל\"הכנסה אחרת\" (62א(ג1))")
    if ci.structure.applies_62a and 0.20 <= s62.governing_profitability <= 0.30:
        out.append("רווחיות בטווח 20%–30% – קרובה לסף 25%; לאמת מול הסימולטור של רשות המסים")
    if ret.exempt_sources_total > 0:
        out.append("רווחים ממקור פטור – לאמת את בחירת החלופה (81ג(ג)) מול רו\"ח")
    if ci.s62a.intercompany_dividend_received > 0:
        out.append("דיבידנד בין-חברתי – לבדוק תחולת תקנות הדיבידנדים (בעלי מניות 126(ב))")
        if ci.s62a.holding_rate_in_paying_company is None:
            out.append("דיבידנד בין-חברתי ללא שיעור החזקה בחברה המחלקת – להשלים (62א(א3))")
    if ret.exempt_sources_total > 0 and sh.special_assets_net > 0:
        out.append("חלופה (1) לרווחים פטורים: עלות הנכסים המיוחדים נלקחת לתום השנה הנבדקת (פישוט) – לאמת")
    if _roll_lag(ci) >= 2:
        need = [y for y, v in ((ci.structure.previous_year - 1, ci.retained.prev2_year_profit_for_rollover), (ci.structure.previous_year, ci.retained.prev_year_profit_for_rollover)) if v is None]
        out.append(f"תרחיש ג׳ – הדוח הסגור האחרון הוא {ci.structure.last_closed_report_year}: העודפים לתום {ci.structure.previous_year} ורווחי יום התחילה (תום 2024) הם אומדן גלגול שנתיים"
                   + (f" ({_rolled_start_day(ci):,.0f})" if _rolled_start_day(ci) is not None and not ci.distributions.retained_at_start_day else "")
                   + ("; " + ret.rollover_note if ret.rollover_note else "")
                   + (f"; חסר רווח {', '.join(map(str, need))} (מאזן בוחן מלא) לגלגול" if need else ""))
    elif ci.is_estimate or ci.structure.is_scenario_b:
        out.append("תרחיש ב׳ – נתוני הבסיס הם אומדן גלגול, לא דוח סגור" + ("; " + ret.rollover_note if ret.rollover_note else "; להזין רווח השנה הקודמת (מאזן בוחן) לגלגול אוטומטי"))
    if s62.concentration_met_by_data and not ci.s62a.concentration_test_met:
        out.append(f"ריכוזיות: לפי כרטסות {s62.concentration_years[0]}–{s62.concentration_years[-1]} – {s62.concentration_top_name} {s62.concentration_share_36m:.0%} "
                   "מסך 36 החודשים → המבחן מתקיים לפי הנתונים: ייחוס מלא. לאשר (או לסמן ידנית אם לא)")
    elif s62.concentration_share >= 0.70 and not s62.concentration_test_met:
        n = len(s62.concentration_years)
        out.append(f"ריכוזיות: {s62.concentration_top_name} – {s62.concentration_share:.0%} מההכנסות השנה"
                   + (f"; על פני {n} שנים ({s62.concentration_years[0]}–{s62.concentration_years[-1]}): {s62.concentration_share_36m:.0%}" if n > 1 else "")
                   + f". המבחן הוא 70% על סך 36 חודשים – חסרות כרטסות של {3 - n} שנים" if n < 3 else ". מתחת ל-70% על 36 חודשים – המבחן לא מתקיים")
    if ci.structure.applies_62a and s62.attributed_income > 0 and ci.s62a.owner_salary_current_year is None:
        out.append("לא הוזן שכר בעלים – עלות המס הנוספת לפי מס שולי משוקלל; להזין שכר לחישוב לפי מדרגות")
    return out


def _next_year(ci: ClientInput, ret: RetainedResult, s62: Section62AResult, c81: Calc81Result,
               tr: TransitionResult, sim: SimulatorResult) -> list[str]:
    """אברהם 14.10 (22) + סבב 2 (2): על בסיס עודפי השנה הקודמת ורווח השנה – פעולות שאפשר להתחיל כבר השנה."""
    st, d = ci.structure, ci.distributions
    ty, ny = st.tax_year, st.tax_year + 1
    out: list[str] = []
    if not st.applies_81 and not st.applies_62a:
        return out
    m = ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month < 12 else 0
    months_left = 12 - m if m else 12
    if st.applies_81:
        p = d.current_year_profit_estimate
        growth = (p * (1 - ci.s62a.corporate_tax_rate) if p and p > 0 else 0.0) - d.dividends_taxed_current_year
        proj = max(0.0, c81.taxable_retained + growth - c81.governing_shield - c81.transition_reduction)
        headroom = max(0.0, c81.governing_shield + c81.transition_reduction - c81.taxable_retained)
        est_end = ret.retained_for_81a + growth
        out.append(f"אומדן עודפים לתום {ty}: {_ils(est_end)} (עודפי {st.previous_year} {_ils(ret.retained_for_81a)}"
                   + (f" + רווח {ty} אחרי מס {_ils(p * (1 - ci.s62a.corporate_tax_rate))}" if p and p > 0 else "")
                   + (f" − דיבידנד {ty} {_ils(d.dividends_taxed_current_year)}" if d.dividends_taxed_current_year else "") + ").")
        if tr.protected_in_tax_year and tr.protected_until_year < ny:
            out.append(f"הגנת הוראת המעבר פוקעת בסוף {tr.protected_until_year} – ב-{ny} החברה נחשפת לתוספת המס על בסיס עודפי {ty}. "
                       f"כדאי להתחיל לפעול כבר השנה.")
        elif tr.protected_in_tax_year:
            out.append(f"מוגנת גם ב-{ny} (עד {tr.protected_until_year}).")
        if not (tr.protected_in_tax_year and tr.protected_until_year >= ny) and proj > 0:
            out.append(f"ללא פעולה ב-{ty}: רווחים עודפים צפויים ב-{ny} של כ-{_ils(proj)} ותוספת מס של כ-{_ils(0.02 * proj)}.")
            six = c81.required_distribution_rate * est_end
            out.append(f"לחלק עוד ב-{ty}: דיבידנד של כ-{_ils(six)} ({c81.required_distribution_rate:.0%} מאומדן העודפים לתום {ty}) "
                       f"שומר על הפטור ב-{ny}" + (f"; השנה עצמה דורשת {_ils(sim.gap_to_close)} לסגירת הפער." if sim.action_required else "."))
        elif headroom > 0 and c81.excess_profits <= 0:
            out.append(f"המגן הקובע ({_ils(c81.governing_shield)}) גדול מהרווחים הנצברים ב-{_ils(headroom)} – "
                       f"גם אחרי רווח {ty} אין חשיפה צפויה ב-{ny} כל עוד ההוצאות נשארות ברמה דומה.")
    if st.applies_62a and s62.attributed_income > 0:
        out.append(f"שכר בעלים מעכשיו: כ-{_ils(s62.attributed_income / months_left)} לחודש ל-{months_left} החודשים שנותרו ב-{ty} "
                   f"(במקום תיקון של {_ils(s62.attributed_income)} בדצמבר) מוריד את הרווחיות ל-25% ומגדיל את מגן ההוצאות של 81. "
                   f"ב-{ny}: כ-{_ils(s62.attributed_income / 12)} לחודש לאורך השנה.")
    elif st.applies_62a and s62.governing_profitability > ci.flags.profitability_warning_threshold:
        out.append(f"רווחיות {s62.governing_profitability:.0%} – לעקוב רבעונית; מעל 25% נדרש תיקון שכר.")
    return out


# ---------------------------------------------------------------------------
# נקודת הכניסה
# ---------------------------------------------------------------------------
# שדות שבלעדיהם התוצאה חסרת משמעות (החלטה 5). המנוע מחשב בכל מקרה ומזהיר.
def _missing_fields(ci: ClientInput) -> list[str]:
    out = []
    if not ci.retained.balance_sheet_retained_earnings and not ci.retained.cumulative_taxable_income:
        out.append("יתרת העודפים במאזן הסגור האחרון")
    if not ci.shields.expenses_current_year:
        out.append("הוצאות השנה הנבדקת")
    if not ci.s62a.total_revenue:
        out.append("סך ההכנסות")
    if not ci.s62a.taxable_income_personal_effort:
        out.append("הכנסה חייבת מפעילות עתירת יגיעה אישית")
    return out


def _annualize(ci: ClientInput, tb_based: bool = False) -> tuple[ClientInput, float]:
    """החלטה 4: נתוני השנה הנבדקת עד חודש N → הערכה שנתית לינארית (× 12 ÷ N).
    tb_based (סבב 4): כשיש טבלת מאזן בוחן, ההכנסות/ההוצאות/הרווח כבר שנתיים מסכום 12 התאים – מוכפלים רק השדות שלא מהטבלה (כרטסת, אחרים)."""
    m = ci.data_through_month
    if not m or not (1 <= m < 12):
        return ci, 1.0
    f = 12.0 / m
    keep = lambda v: v if tb_based else v * f
    s = replace(ci.s62a,
                total_revenue=keep(ci.s62a.total_revenue),
                other_interest=keep(ci.s62a.other_interest),
                other_dividend=ci.s62a.other_dividend * f,
                other_rent=ci.s62a.other_rent * f,
                other_asset_sale=ci.s62a.other_asset_sale * f,
                other_securities_inventory_sale=ci.s62a.other_securities_inventory_sale * f,
                other_real_estate_sale=ci.s62a.other_real_estate_sale * f,
                other_misc_income=keep(ci.s62a.other_misc_income),
                taxable_income_personal_effort=keep(ci.s62a.taxable_income_personal_effort),
                related_company_payments=ci.s62a.related_company_payments * f,
                top_customers=[{**c, "amount": float(c.get("amount") or 0) * f} for c in (ci.s62a.top_customers or [])])
    sh = replace(ci.shields, expenses_current_year=keep(ci.shields.expenses_current_year))
    d = ci.distributions
    if d.current_year_profit_estimate is not None and not tb_based:   # אומדן הרווח – תזרים, מוכפל גם הוא
        d = replace(d, current_year_profit_estimate=d.current_year_profit_estimate * f)
    # דיבידנדים, הפסדים ויתרות מאזן – ערכים בפועל, לא מוכפלים
    return replace(ci, s62a=s, shields=sh, distributions=d), f


def _ils(x: float) -> str:
    return f"{x:,.0f} ₪"


def _recommendation_text(ci: ClientInput, s62: Section62AResult, c81: Calc81Result,
                         sim: SimulatorResult, tr: TransitionResult) -> str:
    """החלטה 12: המערכת מנסחת המלצה. אברהם מאשר/עורך לפני שזה יוצא ללקוח."""
    st = ci.structure
    p: list[str] = []
    if not st.applies_81 and not st.applies_62a:
        return "החוק אינו חל על החברה (אינה חברת מעטים). אין פעולה נדרשת."
    # --- 81
    if tr.protected_in_tax_year and c81.surtax == 0:
        p.append(f"מסלול 81: החברה מוגנת לפי הוראת המעבר עד {tr.protected_until_year} "
                 f"(חילקה {tr.determining_period_rate:.0%} מהרווחים הנצברים בתקופה הקובעת). אין צורך בחלוקה השנה.")
    elif c81.is_exempt:
        p.append("מסלול 81: החברה עומדת במבחן פטור השנה – אין תוספת מס ואין צורך בחלוקה נוספת.")
    elif c81.excess_profits <= 0:
        p.append(f"מסלול 81: המגן הקובע ({_ils(c81.governing_shield)}) מכסה את הרווחים הנצברים החייבים – אין רווחים עודפים ואין תוספת מס.")
    else:
        p.append(f"מסלול 81: רווחים עודפים של {_ils(c81.excess_profits)} אחרי מגן של {_ils(c81.governing_shield)}. "
                 f"ללא פעולה – תוספת מס של {_ils(c81.surtax)} (2%), וזה חוזר כל שנה.")
        p.append(f"לפטור השנה נדרש דיבידנד של {_ils(sim.min_dividend)} ({sim.cheaper_option}); "
                 f"חולקו {_ils(sim.already_distributed)}, הפער לסגירה עד 31.12 הוא {_ils(sim.gap_to_close)}. "
                 f"מס הדיבידנד על הפער: {_ils(sim.dividend_tax_cost)} "
                 f"({'זול' if sim.dividend_tax_cost < sim.surtax_if_not_distributing else 'יקר'} מתוספת המס השנה"
                 + (f"; מתאזן אחרי {sim.years_to_breakeven:.1f} שנים" if sim.years_to_breakeven else "") + ").")
        if sim.surtax_if_salary_paid is not None and sim.surtax_if_salary_paid < c81.surtax:
            p.append(f"תשלום שכר התיקון של 62א עד 31.12 מגדיל את מגן ההוצאות ומוריד את תוספת המס "
                     f"מ-{_ils(c81.surtax)} ל-{_ils(sim.surtax_if_salary_paid)}.")
    # --- 62a
    if not st.applies_62a:
        p.append("מסלול 62א: הסעיף אינו חל (מפעל מועדף/מאושר).")
    elif s62.concentration_test_met:
        p.append(f"מסלול 62א: מבחן הריכוזיות מתקיים – כל ההכנסה החייבת מעתירת יגיעה אישית ({_ils(s62.attributed_income)}) מיוחסת לבעל המניות במס שולי.")
    elif s62.section_applies:
        p.append(f"מסלול 62א: רווחיות של {s62.governing_profitability:.1%} מעל סף 25%. "
                 f"הכנסה מיוחסת של {_ils(s62.attributed_income)} – עלות מס נוספת מוערכת {_ils(s62.extra_tax_cost)}. "
                 f"תשלום שכר לבעל המניות הפעיל בגובה {_ils(s62.attributed_income)} עד 31.12 מוריד את הרווחיות ל-25%.")
    elif s62.crossed_25pct:
        p.append(f"מסלול 62א: רווחיות {s62.governing_profitability:.1%}, אך הסעיף אינו חל "
                 f"({'פטור 750 אלף' if s62.exemption_750k_applies else 'מחזור מעל הסף'}).")
    elif s62.governing_profitability > ci.flags.profitability_warning_threshold:
        p.append(f"מסלול 62א: רווחיות {s62.governing_profitability:.1%} – מתחת לסף אך קרוב. לעקוב עד סוף השנה.")
    else:
        p.append(f"מסלול 62א: רווחיות {s62.governing_profitability:.1%} – מתחת לסף.")
    return " ".join(p)


def what_if(ci: ClientInput, extra_dividend: float = 0.0, salary: float = 0.0) -> "ClientResult":
    """החלטה 9: סימולציה – מה קורה לשני המסלולים אם מחלקים עוד דיבידנד ו/או משלמים שכר עד 31.12.

    שכר = הוצאה: מקטין את ההכנסה החייבת מעתירת יגיעה אישית (62א) ומגדיל את הוצאות השנה (מגן ב', 81).
    דיבידנד: מתווסף לדיבידנדים ששולם עליהם מס השנה (מבחני הפטור ובסיס תוספת המס).
    """
    d = replace(ci.distributions, dividends_taxed_current_year=ci.distributions.dividends_taxed_current_year + extra_dividend)
    # השכר הוא סכום שנתי (עד 31.12). כשהנתונים הם עד חודש N, המנוע מכפיל את תזרימי השנה פי 12/N –
    # לכן מכניסים את השכר מחולק באותו מקדם, כך שאחרי ההכפלה הוא שווה בדיוק לסכום שהוזן.
    _, factor = _annualize(ci)
    salary_ytd = salary / factor
    s = replace(ci.s62a, taxable_income_personal_effort=max(0.0, ci.s62a.taxable_income_personal_effort - salary_ytd))
    sh = replace(ci.shields, expenses_current_year=ci.shields.expenses_current_year + salary_ytd,
                 pay_62a_salary_by_year_end=False)   # השכר כבר בתוך ההוצאות – לא לספור פעמיים
    return compute(replace(ci, distributions=d, s62a=s, shields=sh))


MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _adj_for(ci: ClientInput, key: str, month) -> dict | None:
    for a in ci.adjustments or []:
        if a.get("key") == key and (a.get("month") or None) == (month or None):
            return a
    return None


def _monthly_gaps(ci: ClientInput) -> tuple[ClientInput, list[dict], dict]:
    """סבב 3: חורים חודשיים במאזן הבוחן (חודש בלי שכר כשבשאר החודשים יש) – על הנתונים הגולמיים, לפני ההכפלה.
    סדר עדיפויות: קובץ ← אומדן המערכת (ממוצע החודשים המלאים) ← תיקון של רואה החשבון (אשר / תקן / לא חסר)."""
    bm = ci.period_breakdown_months or {}
    m_last = ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month <= 12 else 12
    items: list[dict] = []
    add_exp = 0.0
    table: dict[str, list] = {}
    for cat, months in bm.items():
        vals = [float(x or 0) for x in list(months)[:12]] + [0.0] * (12 - len(months))
        table[cat] = [vals[i] if i < m_last else None for i in range(12)]
        if cat == "קניות":
            continue                                   # קניות משתנות – אין "חור"
        filled = [v for v in vals[:m_last] if abs(v) > 0.5]
        if len(filled) < 2:
            continue
        avg = sum(filled) / len(filled)
        for i in range(m_last):
            if abs(vals[i]) > 0.5:
                continue
            key, month = cat, i + 1
            adj = _adj_for(ci, key, month)
            label = f"{cat} · {MONTHS_HE[i]}: 0 – בשאר החודשים ממוצע {avg:,.0f} ₪"
            if adj and adj.get("kind") == "dismissed":
                items.append({"key": key, "month": month, "label": label, "amount": 0.0, "estimate": avg, "status": "dismissed", "note": adj.get("note", "")})
            elif adj and adj.get("kind") in ("manual", "accepted"):
                amt = float(adj.get("amount") or 0)
                add_exp += amt
                items.append({"key": key, "month": month, "label": label, "amount": amt, "estimate": avg, "status": "corrected" if adj["kind"] == "manual" else "accepted", "note": adj.get("note", "")})
            else:
                add_exp += avg
                items.append({"key": key, "month": month, "label": label, "amount": avg, "estimate": avg, "status": "pending", "note": ""})
    # תיקונים ידניים שאינם "חור" שהמערכת זיהתה (למשל הוספת סכום לחודש מלא) – נכנסים גם הם
    for a in ci.adjustments or []:
        if a.get("kind") == "manual" and a.get("month") and not any(it["key"] == a.get("key") and it["month"] == a.get("month") for it in items):
            amt = float(a.get("amount") or 0)
            add_exp += amt
            items.append({"key": a.get("key"), "month": a.get("month"), "label": f"{a.get('key')} · {MONTHS_HE[int(a['month']) - 1]}: תוספת ידנית", "amount": amt, "estimate": 0.0, "status": "corrected", "note": a.get("note", "")})
    if add_exp:
        ci = replace(ci,
                     shields=replace(ci.shields, expenses_current_year=ci.shields.expenses_current_year + add_exp),
                     s62a=replace(ci.s62a, taxable_income_personal_effort=max(0.0, ci.s62a.taxable_income_personal_effort - add_exp)),
                     distributions=replace(ci.distributions, current_year_profit_estimate=(ci.distributions.current_year_profit_estimate - add_exp) if ci.distributions.current_year_profit_estimate is not None else None))
    return ci, items, table


COGS_SECTIONS = ("עלויות ייצור", "עלות המכירות", "עלות המכר", "עלות מכירות", "עלות ההכנסות")


def _tb_is_approved(ci: ClientInput) -> bool:
    """אברהם 15.10: "אשר הכל" במאזן הבוחן תקף כל עוד חודש הנתונים לא השתנה (קובץ חדש = אומדנים חדשים לבדיקה)."""
    a = ci.tb_approved or {}
    m = ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month <= 12 else 12
    return bool(ci.tb_rows) and bool(a) and int(a.get("through_month") or 0) == m


COGS_NAME_KEYS = ("עלות", "פרויקט", "חומרי", "יבוא", "קניות")
OTHER_INCOME_KEYS = ("הכנסות אחרות", "רווחים אחרים", "מענק", "החזר", "פיצוי", "מילואים")


def _is_cogs_default(r: dict) -> bool:
    """15.10: עלות המכר כברירת מחדל = קניות, קבלני משנה ושורות שבשמן עלות/פרויקט/חומרים/יבוא. לא לפי הסעיף בריווחית –
    ריווחית שמה שם גם שכר, רכב ואחזקה (אצל לקוח שירותים הרווח הגולמי יצא 38% מול 97% בדוח). אברהם מוסיף/מוריד בכפתור."""
    if r.get("income") or r.get("kind") != "expense":
        return False
    return r.get("category") in ("קניות", "קבלני משנה") or any(k in (r.get("name") or "") for k in COGS_NAME_KEYS)


def _row_kind(r: dict) -> str:
    """סיווג הכנסה מחדש (גם ללקוחות שכבר נקלטו): "הכנסות אחרות" לפי הקבוצה/השם – מענקים, החזרים – אינן הכנסה מהעסק."""
    k = r.get("kind") or ""
    if r.get("income") and k == "revenue":
        txt = " ".join(str(r.get(x) or "") for x in ("section", "group", "name"))
        if any(w in txt for w in OTHER_INCOME_KEYS):
            return "other_income"
    return k


# 22.10 (בדיקה לאחור על שנים שלמות): בסיס האומדן לשורה סדירה
MONTHLY_CATS = ("שכר", "עלויות מעסיק", "שכירות", "דמי ניהול")      # סעיפים שאמורים להופיע כל חודש – 0 בחודש שעבר = "חור"
TREND_CATS = ("שכר", "עלויות מעסיק")                                 # מגמה (העלאות) – ממוצע שלושת החודשים האחרונים


def _robust_base(eff: list[float], filled: list[int], trend: bool = False, keep_idx: set | None = None) -> float:
    """ממוצע החודשים המלאים בלי חודש חריג (פי 3 מהחציון ומעלה). שכר / עלויות מעסיק – שלושת החודשים האחרונים (מגמה)."""
    vals = [eff[i] for i in filled]
    if not vals:
        return 0.0
    srt = sorted(vals)
    med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
    keep = [i for i in filled if i in (keep_idx or ()) or not (med > 0 and eff[i] > 3 * med)] if len(vals) >= 4 else list(filled)
    if trend and len(keep) >= 3:
        keep = keep[-3:]
    keep = keep or filled
    return sum(eff[i] for i in keep) / len(keep)


def _cycle_of(filled: list[int], prev_filled: list[int], m_last: int = 12) -> int | None:
    """זיהוי מחזור תשלום: חודשים עם תנועה במרווח קבוע k (2/3/4/6).
    שלושה תשלומים במרווח זהה; או שניים במרווח זהה כשהתשלום הבא במחזור עוד לא הגיע (אין פעימה שהוחמצה) – אברהם 15.10;
    או אחד השנה כשהשנה הקודמת מחזורית באותו שלב."""
    def gaps_of(idx):
        return [b - a for a, b in zip(idx, idx[1:])]
    g = gaps_of(filled)
    if len(filled) >= 3 and len(set(g)) == 1 and g[0] in (2, 3, 4, 6):
        return g[0]
    if len(filled) == 2 and g[0] in (2, 3, 4, 6) and filled[1] + g[0] >= m_last:
        return g[0]
    pg = gaps_of(prev_filled)
    prev_k = pg[0] if len(prev_filled) >= 2 and len(set(pg)) == 1 and pg[0] in (2, 3, 4, 6) else None
    if len(filled) == 2 and g[0] in (2, 3, 4, 6) and prev_k == g[0]:
        return g[0]
    if len(filled) == 1 and prev_k and (filled[0] % prev_k) == (prev_filled[0] % prev_k):
        return prev_k
    return None


def _tb_table(ci: ClientInput) -> tuple[ClientInput, list[dict], dict | None, dict]:
    """סבב 4 (אברהם, 15.10): מאזן הבוחן המלא – כל שורה × 12 חודשים.
    תא = קובץ / אומדן (חודש שטרם הוזן) / חור (0 בחודש כשהשאר מלאים) / תיקון של רואה החשבון.
    השנה = סכום 12 התאים – במקום הכפלה לינארית. אומדן: לפי אותו חודש במאזן הבוחן של השנה הקודמת מותאם לקצב השנה (עונתיות);
    אין שנה קודמת – ממוצע החודשים שיש (שורה סדירה) או חלק יחסי (שורה לא סדירה)."""
    rows = ci.tb_rows or []
    if not rows:
        return ci, [], None, {}
    m_last = ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month <= 12 else 12
    prev_by_id = {str(r.get("id")): r for r in (ci.tb_rows_prev_year or [])}
    prev_by_name = {str(r.get("name")): r for r in (ci.tb_rows_prev_year or [])}
    out_rows: list[dict] = []
    items: list[dict] = []
    stats = {"file": 0.0, "estimate": 0.0, "correction": 0.0, "season_rows": 0, "avg_rows": 0}
    approved = _tb_is_approved(ci)
    cogs_over = {str(k): bool(v) for k, v in (ci.tb_cogs or {}).items()}
    kind_over = {str(k): v for k, v in (ci.tb_kind or {}).items() if v in ("revenue", "other_income", "fin_income")}
    for r in rows:
        r = {**r, "kind": kind_over.get(str(r.get("id"))) if (r.get("income") and str(r.get("id")) in kind_over) else _row_kind(r)}
        inc = bool(r.get("income"))
        raw = [float(x or 0) for x in list(r.get("months") or [])[:12]] + [0.0] * (12 - len(r.get("months") or []))
        disp = [(-v if inc else v) for v in raw]                           # הכנסות בזכות – מוצגות חיוביות
        key = f"tb:{r.get('id')}"
        # אברהם 15.10: תיקון על חודש שכבר עבר (ינואר–אוגוסט) משנה גם את הבסיס לאומדן החודשים הבאים
        eff = list(disp)
        manual_idx: set[int] = set()
        for i in range(12):
            if i < m_last or abs(disp[i]) > 0.5:
                a0 = _adj_for(ci, key, i + 1)
                if a0 and a0.get("kind") == "manual":
                    eff[i] = float(a0.get("amount") or 0)
                    manual_idx.add(i)                                          # תיקון של אברהם – מכוון, לא "חודש חריג"
        filled = [i for i in range(m_last) if abs(eff[i]) > 0.5]
        # "חור" (0 בחודש כשהשאר מלאים) נבדק רק בשורות שאמורות להיות כל חודש: הכנסות וסעיפי השלמות (שכר, עלויות מעסיק, שכירות…)
        # שורה שלילית (החזרים, למשל "החזר מילואים") – אינה סעיף חודשי; בלי חורים, אומדן לפי קצב
        regular = len(filled) >= max(2, round(0.6 * m_last)) and (inc or r.get("category") not in (None, "קניות")) and sum(eff[:m_last]) > 0
        # 22.10 (בדיקה לאחור): "חור" רק בסעיפים שבאמת חודשיים – שכר, עלויות מעסיק, שכירות, דמי ניהול; לא הכנסות ולא קבלני משנה
        monthly = (not inc) and r.get("category") in MONTHLY_CATS and regular
        # מענקים / הכנסות אחרות, וגם החזרים (שורת הוצאה שלילית) – בלי אומדן לחודשים הבאים
        one_off = r.get("kind") == "other_income" or (not inc and sum(eff[:m_last]) < -0.5)
        # הכנסות: קצב השנה (כולל חודשים בלי הכנסה – הכנסות לא סדירות, אין "חודש חריג"); הוצאות סדירות: ממוצע בלי חודש חריג, שכר – מגמה
        avg = (sum(eff[:m_last]) / m_last if m_last else 0.0) if inc else _robust_base(eff, filled, trend=r.get("category") in TREND_CATS, keep_idx=manual_idx)
        linear = sum(eff[:m_last]) / m_last if m_last else 0.0
        if not inc and len(filled) >= 4 and linear > 0:                      # 22.10: תשלום חריג חד-פעמי לא נכנס לקצב החודשים הבאים
            vals = sorted(eff[i] for i in filled)
            med = vals[len(vals) // 2]
            linear = sum(eff[i] for i in range(m_last) if i in manual_idx or not (med > 0 and eff[i] > 3 * med)) / m_last
        prev = prev_by_id.get(str(r.get("id"))) or prev_by_name.get(str(r.get("name")))
        season = None
        if prev:
            pr = [float(x or 0) for x in list(prev.get("months") or [])[:12]] + [0.0] * 12
            pd = [(-v if inc else v) for v in pr[:12]]
            base_prev, base_cur = sum(pd[:m_last]), sum(eff[:m_last])
            full_prev = sum(pd)
            if base_prev > 0.5 and base_cur > 0.5 and any(abs(x) > 0.5 for x in pd[m_last:]):
                ratio = base_cur / base_prev
                # 22.10: היחס לשנה הקודמת מתפוצץ כשעד החודש הזה כמעט לא היה כלום (קניות 70 אלף → אומדן 4.6 מיליון) – אז לא עונתיות
                if base_prev >= 0.15 * full_prev and 1 / 3 <= ratio <= 3:
                    season = [x * ratio for x in pd]
        # מחזורי (אברהם 15.10): תשלום כל k חודשים (חשמל כל חצי שנה, ביטוח רבעוני) – ממשיכים את המחזור במקום ממוצע/חלק יחסי
        cycle = None
        if not season:
            prev_filled = []
            if prev:
                pr0 = [float(x or 0) for x in list(prev.get("months") or [])[:12]] + [0.0] * 12
                prev_filled = [i for i in range(12) if abs(pr0[i]) > 0.5]
            cycle = _cycle_of(filled, prev_filled, m_last)
        if season:
            stats["season_rows"] += 1
        elif cycle:
            stats["cycle_rows"] = stats.get("cycle_rows", 0) + 1
        else:
            stats["avg_rows"] += 1
        cyc_months = set()
        if cycle:
            k = cycle
            last = max(filled) if filled else -1
            m = last + k
            while m < 12:
                cyc_months.add(m)
                m += k
        cells = []
        for i in range(12):
            file_v = disp[i]
            if i < m_last or abs(file_v) > 0.5:
                if abs(file_v) > 0.5 or not monthly:
                    src, v, base = "file", file_v, file_v
                else:                                                      # חור: 0 בחודש שבשאר החודשים יש
                    base = season[i] if season else avg
                    src, v = "gap", base
            else:
                if one_off:
                    base = 0.0
                elif season:
                    base = season[i]
                elif cycle:
                    base = avg if i in cyc_months else 0.0
                else:
                    base = avg if regular else linear          # סעיף מפתח סדיר – ממוצע החודשים המלאים; כל השאר – קצב: סכום עד היום ÷ חודשים
                src, v = "estimate", base
            adj = _adj_for(ci, key, i + 1)
            note = by = at = ""
            if adj:
                note, by, at = adj.get("note", ""), adj.get("by", ""), adj.get("at", "")
                if adj.get("kind") == "manual":
                    v, src = float(adj.get("amount") or 0), "manual"
                elif adj.get("kind") == "dismissed" and src == "gap":
                    v, src = 0.0, "dismissed"
                elif adj.get("kind") == "accepted" and src in ("gap", "estimate"):
                    src = "accepted"
            elif approved and src in ("gap", "estimate"):
                src = "accepted"
            cells.append({"v": round(v), "src": src, "base": round(base), "note": note, "by": by, "at": at})
            if not inc and r.get("kind") == "expense":
                if src == "file":
                    stats["file"] += v
                elif src in ("estimate", "gap", "accepted"):
                    stats["estimate"] += v
                elif src == "manual":
                    stats["correction"] += v - base
            if src in ("gap", "dismissed") or (src in ("manual", "accepted") and i < m_last and abs(file_v) <= 0.5 and monthly):
                st = {"gap": "pending", "dismissed": "dismissed", "manual": "corrected", "accepted": "accepted"}[src]
                items.append({"key": key, "month": i + 1, "label": f"{r.get('name')} · {MONTHS_HE[i]}: 0 – בשאר החודשים {'לפי השנה הקודמת' if season else 'ממוצע'} {base:,.0f} ₪",
                              "amount": v if st != "dismissed" else 0.0, "estimate": base, "status": st, "note": note})
        total = sum(c["v"] for c in cells)
        out_rows.append({"id": r.get("id"), "code": r.get("code", ""), "name": r.get("name"), "section": r.get("section", ""), "group": r.get("group", ""),
                         "income": inc, "kind": r.get("kind", ""), "category": r.get("category"), "cells": cells, "total": round(total),
                         "file_total": round(sum(disp[:m_last])),
                         "cogs": cogs_over.get(str(r.get("id")), _is_cogs_default(r)) if r.get("kind") == "expense" else False,
                         "cogs_default": _is_cogs_default(r),
                         "method": "ללא אומדן" if one_off else ("עונתיות" if season else (f"מחזורי · כל {cycle} חודשים" if cycle else ("ממוצע" if regular else "קצב")))})
    def tot(kind):
        return sum(r["total"] for r in out_rows if r["kind"] == kind)
    revenue, fin, other, expenses = tot("revenue"), tot("fin_income"), tot("other_income"), tot("expense")
    bd = {}
    for r in out_rows:
        if r["kind"] == "expense" and r.get("category"):
            bd[r["category"]] = bd.get(r["category"], 0.0) + r["total"]
    dep = bd.get("פחת", 0.0)
    profit = revenue + fin + other - expenses
    # 62א: "סך ההכנסות" כולל הכל; מימון והכנסות אחרות יורדות ממנו (B12) – ההכנסה מעתירת יגיעה = מכירות בלבד.
    # הכנסה חייבת "מפעילות זו" = מכירות פחות הוצאות, בלי הכנסות מימון/אחרות (15.10; קודם נכללו)
    ci2 = replace(ci,
                  s62a=replace(ci.s62a, total_revenue=revenue + fin + other, other_interest=fin, other_misc_income=other,
                               taxable_income_personal_effort=max(0.0, revenue - expenses),
                               purchases_current_year=(bd.get("קניות") if "קניות" in bd else ci.s62a.purchases_current_year)),
                  shields=replace(ci.shields, expenses_current_year=expenses - dep),
                  distributions=replace(ci.distributions, current_year_profit_estimate=profit),
                  period_breakdown={k: round(v) for k, v in bd.items()})
    sums = {}
    for kind in ("revenue", "fin_income", "other_income", "expense"):
        sums[kind] = [round(sum(r["cells"][i]["v"] for r in out_rows if r["kind"] == kind)) for i in range(12)]
    sums["profit"] = [sums["revenue"][i] + sums["fin_income"][i] + sums["other_income"][i] - sums["expense"][i] for i in range(12)]
    # אברהם 15.10: רווח גולמי = הכנסות ממכירות − עלות המכר (השורות המסומנות "בעלות המכר")
    sums["cogs"] = [round(sum(r["cells"][i]["v"] for r in out_rows if r.get("cogs"))) for i in range(12)]
    sums["gross"] = [sums["revenue"][i] - sums["cogs"][i] for i in range(12)]
    cogs_total = sum(sums["cogs"])
    gross = revenue - cogs_total
    a = ci.tb_approved or {}
    table = {"through_month": m_last, "rows": out_rows, "sums": sums,
             "annual": {"revenue": round(revenue), "fin_income": round(fin), "other_income": round(other), "expenses": round(expenses), "profit": round(profit),
                        "cogs": round(cogs_total), "gross": round(gross), "gross_rate": (gross / revenue) if revenue else None},
             "gross_history": list(ci.s62a.gross_profit_history or []),
             "gross_margin_report": ci.s62a.gross_margin_rate,
             "approved": dict(a) if approved else None,
             "approved_stale": bool(a) and not approved,
             "method": ("לפי מאזן הבוחן של השנה הקודמת (עונתיות)" if stats["season_rows"] and not stats["avg_rows"] else
                        "לפי השנה הקודמת כשיש התאמה, אחרת קצב השנה" if stats["season_rows"] else "קצב השנה – סכום עד היום ÷ חודשים (אין מאזן בוחן של השנה הקודמת)")
                       + (f"; {stats.get('cycle_rows', 0)} סעיפים מחזוריים (תשלום כל כמה חודשים)" if stats.get("cycle_rows") else ""),
             "stats": {k: round(v) if isinstance(v, float) else v for k, v in stats.items()}}
    return ci2, items, table, stats


def _estimates(ci: ClientInput) -> tuple[ClientInput, list[str]]:
    """אברהם (סבב 2, 5–7, 14, 15): השלמות שמאזן בוחן באמצע שנה לא מכיל – על נתונים שנתיים (אחרי ההכפלה).
    כל השלמה נרשמת כאומדן לבדיקת אברהם. 1. פחת לפי הדוח השנתי; 2. התאמת מלאי לפי רווח גולמי; 3. סעיף שהיה בשנה הקודמת ונעלם."""
    notes: list[str] = []
    s, sh, d = ci.s62a, ci.shields, ci.distributions
    bd, bd_prev = ci.period_breakdown or {}, ci.period_breakdown_prev_year or {}
    add_exp = 0.0          # להוצאות למגן
    add_cost = 0.0         # הקטנת הרווח (הכנסה חייבת ואומדן רווח)
    has_period_data = bool(bd) or sh.expenses_current_year > 0 or s.total_revenue > 0
    if not has_period_data:                                   # עוד אין מאזן בוחן לשנה – אין על מה לאמוד
        return ci, notes
    def decide(key: str, est: float, label: str) -> float:
        """תיקון של רואה החשבון גובר על האומדן השנתי: לא חסר → 0; סכום/אישור → הסכום; אחרת האומדן + הערה."""
        adj = _adj_for(ci, key, None)
        if adj and adj.get("kind") == "dismissed":
            return 0.0
        if adj and adj.get("kind") in ("manual", "accepted"):
            return float(adj.get("amount") or 0)
        if _tb_is_approved(ci):                                # "אשר הכל" במאזן הבוחן – האומדן מאושר
            return est
        notes.append(label)
        return est

    if sh.depreciation_annual_estimate and not bd.get("פחת"):
        dep = float(sh.depreciation_annual_estimate)
        v = decide("פחת", dep, f"פחת: מאזן הבוחן בלי פחת – נוסף פחת שנתי {dep:,.0f} ₪ לפי הדוח השנתי (אומדן)")
        add_exp += v
        add_cost += v
    if s.has_inventory and s.gross_margin_rate and s.purchases_current_year is not None and s.total_revenue > 0:
        purchases = float(s.purchases_current_year) * (1.0 if ci.tb_rows else (12.0 / ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month < 12 else 1.0))
        cogs = s.total_revenue * (1 - s.gross_margin_rate)
        delta = cogs - purchases                                 # חיובי = עלות המכר גבוהה מהקניות (המלאי ירד)
        v = decide("מלאי", delta, f"מלאי: במקום קניות {purchases:,.0f} ₪ – עלות מכר לפי רווח גולמי {s.gross_margin_rate:.1%} (ממוצע שתי השנים שבדוח): "
                   f"{cogs:,.0f} ₪; הרווח {'קטן' if delta > 0 else 'גדל'} ב-{abs(delta):,.0f} ₪ (אומדן, אין ספירת מלאי)")
        add_exp += v
        add_cost += v
    for cat, v_prev in bd_prev.items():
        v_prev = float(v_prev or 0)
        if bd and v_prev > 0 and not bd.get(cat) and cat not in ("פחת", "קניות"):
            v = decide(f"{cat}:שנה", v_prev, f"חסר השנה: {cat} – בשנה הקודמת {v_prev:,.0f} ₪; נוסף כאומדן שנתי (לבדוק אם חסר רישום)")
            add_exp += v
            add_cost += v
    if not add_exp and not add_cost:
        return ci, notes
    s2 = replace(s, taxable_income_personal_effort=max(0.0, s.taxable_income_personal_effort - add_cost))
    sh2 = replace(sh, expenses_current_year=max(0.0, sh.expenses_current_year + add_exp))
    d2 = replace(d, current_year_profit_estimate=d.current_year_profit_estimate - add_cost) if d.current_year_profit_estimate is not None else d
    return replace(ci, s62a=s2, shields=sh2, distributions=d2), notes


def _annual_item_keys(ci: ClientInput, notes: list[str]) -> list:
    """פריטי האומדן השנתיים (פחת / מלאי / סעיף שנעלם) כפריטים עם סטטוס – לטבלת החוסרים בכרטיס."""
    out = []
    s, sh = ci.s62a, ci.shields
    bd, bd_prev = ci.period_breakdown or {}, ci.period_breakdown_prev_year or {}
    has_data = bool(bd) or sh.expenses_current_year > 0 or s.total_revenue > 0
    if not has_data:
        return out

    def item(key, label, est):
        adj = _adj_for(ci, key, None)
        st = "pending"
        amt = est
        if adj and adj.get("kind") == "dismissed":
            st, amt = "dismissed", 0.0
        elif adj and adj.get("kind") in ("manual", "accepted"):
            st, amt = ("corrected" if adj["kind"] == "manual" else "accepted"), float(adj.get("amount") or 0)
        elif _tb_is_approved(ci):
            st = "accepted"
        return (key, {"key": key, "month": None, "label": label, "amount": amt, "estimate": est, "status": st, "note": (adj or {}).get("note", "")})

    if sh.depreciation_annual_estimate and not bd.get("פחת"):
        out.append(item("פחת", f"פחת שנתי לפי הדוח השנתי: {float(sh.depreciation_annual_estimate):,.0f} ₪ (במאזן הבוחן אין פחת)", float(sh.depreciation_annual_estimate)))
    if s.has_inventory and s.gross_margin_rate and s.purchases_current_year is not None and s.total_revenue > 0:
        f = 1.0 if ci.tb_rows else (12.0 / ci.data_through_month if ci.data_through_month and 1 <= ci.data_through_month < 12 else 1.0)
        purchases = float(s.purchases_current_year) * f
        delta = s.total_revenue * (1 - s.gross_margin_rate) - purchases
        cogs = s.total_revenue * (1 - s.gross_margin_rate)
        out.append(item("מלאי", f"התאמת מלאי: קניות בקובץ {purchases:,.0f} ₪ ← עלות מכר לפי רווח גולמי {s.gross_margin_rate:.1%} (מהדוח השנתי) {cogs:,.0f} ₪ ← הפרש {abs(delta):,.0f} ₪ {'נוסף להוצאות (הרווח קטן)' if delta > 0 else 'יורד מההוצאות (הרווח גדל)'}", delta))
    for cat, v_prev in bd_prev.items():
        v_prev = float(v_prev or 0)
        if bd and v_prev > 0 and not bd.get(cat) and cat not in ("פחת", "קניות"):
            out.append(item(f"{cat}:שנה", f"{cat}: אין השנה בכלל – בשנה הקודמת {v_prev:,.0f} ₪", v_prev))
    return out


def _years_used(ci: ClientInput, s62) -> dict:
    st = ci.structure
    closed = st.last_closed_report_year or st.previous_year
    return {
        "retained": f"דוח {closed}" + (f" מגולגל ל-{st.previous_year} (אומדן{', שנתיים' if _roll_lag(ci) >= 2 else ''})" if st.is_scenario_b else ""),
        "expenses_avg": f"{st.tax_year - 2}–{st.tax_year}",
        "current_year": f"{st.tax_year}" + (f" עד חודש {ci.data_through_month} (אומדן שנתי)" if ci.data_through_month and ci.data_through_month < 12 else ""),
        "concentration": (f"{s62.concentration_years[0]}–{s62.concentration_years[-1]}" if len(s62.concentration_years) > 1 else (str(s62.concentration_years[0]) if s62.concentration_years else "אין כרטסת")) + f" ({len(s62.concentration_years)} מתוך 3 שנים)",
    }


def compute(ci: ClientInput) -> ClientResult:
    from . import LOGIC_VERSION

    missing = _missing_fields(ci)
    actuals = {"through_month": ci.data_through_month, "revenue": ci.s62a.total_revenue,
               "taxable_income": ci.s62a.taxable_income_personal_effort, "expenses": ci.shields.expenses_current_year,
               "profit_estimate": ci.distributions.current_year_profit_estimate}
    file_exp = ci.shields.expenses_current_year
    months_table = None
    if ci.tb_rows:                                                  # סבב 4: המסמך המלא קובע – השנה = סכום 12 התאים
        ci, month_items, months_table, tb_stats = _tb_table(ci)
        gap_table = {}
        ci, factor = _annualize(ci, tb_based=True)
        file_exp, est_m, corr_m = tb_stats["file"], tb_stats["estimate"], tb_stats["correction"]
    else:
        ci, month_items, gap_table = _monthly_gaps(ci)
        ci, factor = _annualize(ci)
        corr_m = sum(it["amount"] for it in month_items if it["status"] in ("corrected", "accepted"))
        est_m = sum(it["amount"] for it in month_items if it["status"] == "pending")
    exp_before_annual_est = ci.shields.expenses_current_year
    ci, est_notes = _estimates(ci)
    est_annual = ci.shields.expenses_current_year - exp_before_annual_est
    # אומדנים שנתיים (פחת/מלאי/סעיף שנעלם) – פריטים עם סטטוס לפי התיקונים
    annual_items = []
    for key, note in _annual_item_keys(ci, est_notes):
        annual_items.append(note)
    all_items = month_items + annual_items
    _, _, _, _, retained_for_81a = _retained_base(ci)
    s62 = _section_62a(ci, retained_for_81a)
    sh = _shields(ci, s62.attributed_income)
    ret = _retained_full(ci, sh.special_assets_net)
    tr = _transition(ci)
    c81 = _calc81(ci, ret, sh, tr)
    sim = _simulator(ci, ret, tr, c81)
    # החלטה 10: השפעת תשלום שכר התיקון על תוספת המס (רק אם יש שכר לתיקון ולא סומן שכבר משולם)
    if s62.attributed_income > 0 and not ci.shields.pay_62a_salary_by_year_end and c81.surtax > 0:
        sh2 = _shields(replace(ci, shields=replace(ci.shields, pay_62a_salary_by_year_end=True)), s62.attributed_income)
        ret2 = _retained_full(ci, sh2.special_assets_net)
        sim.surtax_if_salary_paid = _calc81(ci, ret2, sh2, tr).surtax
    dash = _dashboard(ci, s62, tr, c81, sim, missing)
    sim.recommendation_text = _recommendation_text(ci, s62, c81, sim, tr)
    return ClientResult(
        name=ci.structure.name,
        tax_year=ci.structure.tax_year,
        previous_year=ci.structure.previous_year,
        data_as_of=ci.data_as_of,
        is_estimate=ci.is_estimate or ci.structure.is_scenario_b,
        logic_version=LOGIC_VERSION,
        flags=ci.flags,
        applies_81=ci.structure.applies_81,
        applies_62a=ci.structure.applies_62a,
        companies_for_750k_split=ci.structure.companies_for_750k_split,
        retained=ret,
        s62a=s62,
        shields=sh,
        transition=tr,
        calc81=c81,
        simulator=sim,
        dashboard=dash,
        manual_review=_manual_review(ci, ret, s62, sh),
        missing_fields=missing,
        annualization_factor=factor,
        next_year_notes=_next_year(ci, ret, s62, c81, tr, sim),
        actuals=actuals,
        estimate_notes=est_notes + [it["label"] for it in month_items if it["status"] == "pending"],
        estimate_items=all_items,
        data_breakdown={"file": file_exp, "estimates_monthly": est_m, "corrections_monthly": corr_m, "estimates_annual": est_annual, "factor": factor},
        months_gap_table=gap_table,
        years_used=_years_used(ci, s62),
        months_table=months_table,
        scenario_label=scenario_label(ci),
    )
