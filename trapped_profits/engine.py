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
    manual_review_reasons: list[str] = field(default_factory=list)


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# לשונית «רווחים_נצברים» – חלק א-ב (בסיס). חלקים ג-ה אחרי המגנים.
# ---------------------------------------------------------------------------
def _retained_base(ci: ClientInput) -> tuple[float, float, bool, float, float]:
    r = ci.retained
    formula = (r.cumulative_taxable_income or 0.0) + r.cumulative_exempt_income \
        + r.cumulative_land_appreciation - r.cumulative_tax - r.cumulative_dividends \
        - r.uncredited_loss                                                   # B11
    cap = r.balance_sheet_retained_earnings + r.capitalized_profits \
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
    )


# ---------------------------------------------------------------------------
# לשונית «סעיף_62א»
# ---------------------------------------------------------------------------
def _section_62a(ci: ClientInput, retained_for_81a: float) -> Section62AResult:
    s, st = ci.s62a, ci.structure
    other = s.other_interest + s.other_dividend + s.other_rent + s.other_asset_sale \
        + s.other_securities_inventory_sale + s.other_real_estate_sale          # B12
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
    elif s.concentration_test_met:
        attributed = s.taxable_income_personal_effort                           # חסם עליון – ייחוס מלא
    elif applies:
        attributed = max(0.0, s.taxable_income_personal_effort - deduction)
    else:
        attributed = 0.0
    extra_cost = max(0.0, attributed * (s.marginal_tax_rate - s.corporate_tax_rate))  # B34
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
    )


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
    rate = d.dividend_in_determining_period / d.retained_at_start_day \
        if d.retained_at_start_day else 0.0                                          # B21
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
    return Calc81Result(
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
    if d.current_year_profit_estimate is not None:
        p = d.current_year_profit_estimate
        after_tax = p * (1 - ci.s62a.corporate_tax_rate) if p > 0 else p   # על הפסד אין מס
        est = ci.retained.balance_sheet_retained_earnings + after_tax - d.dividends_taxed_current_year

    return SimulatorResult(
        option_6pct=opt6, option_50pct=opt50, cheaper_option=cheaper, min_dividend=min_div,
        already_distributed=already, gap_to_close=gap, dividend_tax_cost=div_tax,
        surtax_if_not_distributing=surtax, difference=diff, years_to_breakeven=years,
        recommendation=rec, action_required=c81.surtax > 0,
        option_20pct_start_day=opt20, estimated_retained_year_end=est,
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
    elif ci.s62a.concentration_test_met:
        status62 = "אדום – מבחן ריכוזיות: ייחוס מלא"
    elif s62.section_applies and s62.attributed_income > 0.5:
        status62 = "אדום – ייחוס הכנסה לבעל המניות"
    elif s62.governing_profitability > f.profitability_warning_threshold:
        status62 = "צהוב – רווחיות מתקרבת לסף 25%"
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
    if ci.is_estimate or ci.structure.is_scenario_b:
        out.append("תרחיש ב׳ – נתוני הבסיס הם אומדן גלגול, לא דוח סגור")
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


def _annualize(ci: ClientInput) -> tuple[ClientInput, float]:
    """החלטה 4: נתוני השנה הנבדקת עד חודש N → הערכה שנתית לינארית (× 12 ÷ N)."""
    m = ci.data_through_month
    if not m or not (1 <= m < 12):
        return ci, 1.0
    f = 12.0 / m
    s = replace(ci.s62a,
                total_revenue=ci.s62a.total_revenue * f,
                other_interest=ci.s62a.other_interest * f,
                other_dividend=ci.s62a.other_dividend * f,
                other_rent=ci.s62a.other_rent * f,
                other_asset_sale=ci.s62a.other_asset_sale * f,
                other_securities_inventory_sale=ci.s62a.other_securities_inventory_sale * f,
                other_real_estate_sale=ci.s62a.other_real_estate_sale * f,
                taxable_income_personal_effort=ci.s62a.taxable_income_personal_effort * f,
                related_company_payments=ci.s62a.related_company_payments * f)
    sh = replace(ci.shields, expenses_current_year=ci.shields.expenses_current_year * f)
    # דיבידנדים, הפסדים ויתרות מאזן – ערכים בפועל, לא מוכפלים
    return replace(ci, s62a=s, shields=sh), f


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
    elif ci.s62a.concentration_test_met:
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


def compute(ci: ClientInput) -> ClientResult:
    from . import LOGIC_VERSION

    missing = _missing_fields(ci)
    ci, factor = _annualize(ci)
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
    )
