"""מודל הקלט – התאים הצהובים באקסל, לשונית אחר לשונית.

כל שדה מסומן בתא המקורי באקסל. ערכים כספיים בש"ח, שיעורים כשבר (0.25 = 25%).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Any


# ---------------------------------------------------------------------------
# דגלים לנקודות הפתוחות (מסמך "נקודות לאישור אברהם")
# ---------------------------------------------------------------------------
@dataclass
class Flags:
    """ברירות המחדל = ההצעה שנשלחה לאברהם. אישור משנה ערך, לא מבנה."""

    # נקודה 1 – רווחי יום התחילה נמדדים לתום איזו שנה (תיעוד בלבד; הערך עצמו הוא קלט)
    start_day_basis_year: int = 2024

    # נקודה 2 – האם להפחית את הרווחים שנותרו מיום התחילה גם מבסיס מבחן ה-50%
    # הסיכום: לא.  האקסל (חישוב_81!B19, סימולטור!B6): כן.
    deduct_transition_from_50pct_base: bool = False

    # נקודה 3 – הוראת מעבר נוספת: חלוקה שוטפת של 20% מהרווחים שנותרו (חלוקות!B15)
    enable_20pct_current_year_rule: bool = True

    # נקודה 6 – בסיס ניכוי ה-25% בהכנסה המיוחסת (62א, שלב 5)
    # הסיכום: 25% × הכנסה מעתירת יגיעה אישית.  האקסל (סעיף_62א!B30): 25% × (הכנסה − תשלומים לחברה קשורה).
    deduction_base_excludes_related_payments: bool = False

    # סף "צהוב" במסלול 62א (דאשבורד!B26)
    profitability_warning_threshold: float = 0.20


# ---------------------------------------------------------------------------
# 1. לשונית «מבנה»
# ---------------------------------------------------------------------------
@dataclass
class CompanyStructure:
    name: str = ""                                   # B5
    company_id: str = ""                             # B6 – ח.פ.
    tax_year: int = 2026                             # B7 – שנת המס הנבדקת
    last_closed_report_year: Optional[int] = None    # שנת הדוח הסגור האחרון; נמוכה משנה קודמת → תרחיש ב׳ (אומדן)
    is_few_holders_company: bool = True              # B11 – חברת מעטים (סעיף 76)
    preferred_or_approved_enterprise: bool = False   # B12 – חמי"ז/חנ"ז/מועדפת/מוטבת/מאושר → שולל 62א
    controlling_owner_name: str = ""                 # החלטה 16: שם בעל השליטה – לקיבוץ בתור (עוד לא חישוב חוצה חברות)
    controlling_owners_count: int = 1                # B17 – בעל שליטה וקרובו נמנים כאחד
    group_companies_count: int = 1                   # B18 – חברות מעטים בשליטת בעל השליטה (כולל זו)
    group_companies_waived: int = 0                  # B19 – חברות שהודיעו על ויתור
    has_material_holder: bool = False                # B22 – מחזיק מהותי 30%+ (מידע; לא בנוסחאות)
    material_holder_total_profits: float = 0.0       # B23 – (מידע; לא בנוסחאות)
    owner_controls_another_company: bool = False     # B24 – יחיד שהוא בעל שליטה בחברה אחרת
    partnership_income_share: float = 0.0            # B27 – שיעור חלק החברה בהכנסות שותפות
    encouragement_law_status: str = "אין"            # B28 – (מידע)

    @property
    def previous_year(self) -> int:                  # B8
        return self.tax_year - 1

    @property
    def is_scenario_b(self) -> bool:
        return self.last_closed_report_year is not None and self.last_closed_report_year < self.previous_year

    @property
    def applies_81(self) -> bool:                    # B13
        return self.is_few_holders_company

    @property
    def applies_62a(self) -> bool:                   # B14
        return self.is_few_holders_company and not self.preferred_or_approved_enterprise

    @property
    def companies_for_750k_split(self) -> int:       # B20
        return max(1, self.group_companies_count - self.group_companies_waived)


# ---------------------------------------------------------------------------
# 2. לשונית «רווחים_נצברים» – לתום שנת המס הקודמת
# ---------------------------------------------------------------------------
@dataclass
class RetainedEarningsInput:
    # א. הנוסחה המיסויית (סעיף 77(א)) – אופציונלי בפיילוט
    cumulative_taxable_income: Optional[float] = None  # B5 – ריק/0 → לוקחים את יתרת העודפים במאזן
    cumulative_exempt_income: float = 0.0              # B6
    cumulative_land_appreciation: float = 0.0          # B7 – שבח
    cumulative_tax: float = 0.0                        # B8
    cumulative_dividends: float = 0.0                  # B9
    uncredited_loss: float = 0.0                       # B10

    # ב. התקרה החשבונאית
    balance_sheet_retained_earnings: float = 0.0       # B14 – יתרת העודפים במאזן (302(ב))
    capitalized_profits: float = 0.0                   # B15
    transparent_entity_profits: float = 0.0            # B16

    attributed_to_shareholders: float = 0.0            # B20 – רווחים שיוחסו לבעל מניות (3(ט1), 62א, 64, 64א)
    # תרחיש ב׳ (הדוח הסגור ישן בשנה): רווח השנה הקודמת לפני מס מהמאזן בוחן – המנוע מגלגל:
    # עודפים לתום השנה הקודמת ≈ עודפי הדוח הסגור + רווח × (1 − מס חברות) − דיבידנד השנה הקודמת. ריק = בלי גלגול.
    prev_year_profit_for_rollover: Optional[float] = None

    # ג. רווחים ממקור פטור – חלופה (1). רלוונטי רק לארבעת המקורות; לכל השאר 0
    exempt_preferred_enterprise_income: float = 0.0    # B24
    exempt_industrial_sales_income: float = 0.0        # B25
    exempt_building_8a_income: float = 0.0             # B26
    exempt_financial_institution_income: float = 0.0   # B27

    # ד. חלופה (2) – 7 שנות המס האחרונות
    exempt_profits_last_7_years: float = 0.0           # B33


# ---------------------------------------------------------------------------
# 3. לשונית «מגנים» – לתום שנת המס הנבדקת
# ---------------------------------------------------------------------------
@dataclass
class ShieldsInput:
    fixed_shield_base: float = 750_000.0               # B5

    # מגן ב' – הוצאות מותרות בניכוי, ללא הוצאות לרכישת נכסים מיוחדים ופחת/מימון בגינם
    expenses_current_year: float = 0.0                 # B10
    expenses_prev_year: float = 0.0                    # B11
    expenses_prev2_year: float = 0.0                   # B12
    pay_62a_salary_by_year_end: bool = False           # B15 – "כן" מוסיף את שכר התיקון להוצאות
    # אברהם (סבב 2, 15): פחת שנתי מהדוח השנתי האחרון – אומדן לשנה השוטפת כשמאזן הבוחן בלי פחת
    depreciation_annual_estimate: Optional[float] = None
    total_assets_cost_is_net: bool = False             # אברהם (סבב 2, 1): אין ביאור רכוש קבוע – נלקח הנטו מהמאזן (לאישור)

    # מגן ג' – נכסים
    total_assets_cost: float = 0.0                     # B17
    special_securities: float = 0.0                    # B20 – ני"ע לרבות מלאי עסקי
    special_financial_asset: float = 0.0               # B21
    special_intangible_royalty: float = 0.0            # B22
    special_real_estate: float = 0.0                   # B23 – זכות במקרקעין
    special_loans_deposits_cash: float = 0.0           # B24
    excl_own_use_real_estate: float = 0.0              # B27
    excl_rental_building: float = 0.0                  # B28
    excl_pledged_cash_financing: float = 0.0           # B29
    excl_regulatory_equity_cash: float = 0.0           # B30
    share_capital_and_premium: float = 0.0             # B33
    related_party_loan: float = 0.0                    # B34
    held_company_cost: float = 0.0                     # B35 – חבר בני אדם מוחזק 10%+


# ---------------------------------------------------------------------------
# 4. לשונית «חלוקות»
# ---------------------------------------------------------------------------
@dataclass
class DistributionsInput:
    # א. השנה הנבדקת
    dividends_taxed_current_year: float = 0.0          # B4 – דיבידנדים ששולם מס בשל חלוקתם
    losses_current_year: float = 0.0                   # B5 – הפסדים לפי 28/29/92

    # ב. בסיס לתום שנה קודמת
    excess_profits_prev_year: float = 0.0              # B9 – רווחים עודפים מהחישוב של השנה שעברה

    # ג. הוראות מעבר – רווחי יום התחילה (סעיף 5)
    start_day_excess_profits: float = 0.0              # B12 – לתום Flags.start_day_basis_year (2024). באקסל הכותרת "תום 2025" – נקודה 1
    start_day_dividends_taxed: float = 0.0             # B13 – דיבידנדים ששולם מס מרווחים אלה

    # ד. התקופה הקובעת 1.1.2025–30.11.2025
    retained_at_start_day: float = 0.0                 # B18 – רווחים נצברים ליום התחילה
    dividend_in_determining_period: float = 0.0        # B19
    determining_period_paid_and_taxed: bool = False    # B20 – שולם בתקופה והמס עד 31.12.2025

    # נקודה 5 – אומדן עודפים עדכני (תצוגה בלבד). אופציונלי
    current_year_profit_estimate: Optional[float] = None
    # תרחיש ב׳: דיבידנד שחולק בשנה הקודמת (כולה) – לגלגול העודפים. אינו במאזן בוחן – ידני
    dividends_prev_year: float = 0.0


# ---------------------------------------------------------------------------
# 5. לשונית «סעיף_62א»
# ---------------------------------------------------------------------------
@dataclass
class Section62AInput:
    total_revenue: float = 0.0                         # B4
    other_interest: float = 0.0                        # B6
    other_dividend: float = 0.0                        # B7
    other_rent: float = 0.0                            # B8
    other_asset_sale: float = 0.0                      # B9
    other_securities_inventory_sale: float = 0.0       # B10
    other_real_estate_sale: float = 0.0                # B11

    taxable_income_personal_effort: float = 0.0        # B16 – אחרי ייחוס הוצאות לפי 62א(ג1)
    related_company_payments: float = 0.0              # B17
    avg_profitability_2023_2025: float = 0.0           # B19 – לשימוש בשנת 2025 בלבד

    marginal_tax_rate: float = 0.50                    # B32
    corporate_tax_rate: float = 0.23                   # B33
    # אברהם 14.10 (10): שכר בעלים ששולם בשנת המס. אם מוזן – עלות המס הנוספת מחושבת לפי מדרגות מס
    # (מס על שכר+הכנסה מיוחסת פחות מס על השכר בלבד); ריק → נופלים למס שולי משוקלל.
    owner_salary_current_year: Optional[float] = None
    # אברהם 14.10 (12): הלקוחות הגדולים – לבדיקת ריכוזיות (70% מגורם אחד). [{"name": "...", "amount": 0}]
    # ידני עד שיגיע מקובץ.
    top_customers: list = field(default_factory=list)
    top_customers_prev_year: list = field(default_factory=list)   # כרטסת השנה הקודמת – ריכוזיות על פני שנתיים
    prev_year_revenue_for_concentration: float = 0.0           # סך הכרטסת של השנה הקודמת (המכנה)
    top_customers_prev2_year: list = field(default_factory=list)  # אברהם (סבב 2, 3): כרטסת שנתיים אחורה – 36 חודשים
    prev2_year_revenue_for_concentration: float = 0.0
    # אברהם (סבב 2, 14): חברה עם מלאי – מאזן בוחן באמצע שנה בלי ספירת מלאי; אומדן רווח לפי רווח גולמי מהדוח השנתי
    has_inventory: bool = False
    gross_margin_rate: Optional[float] = None                  # רווח גולמי ÷ מכירות, ממוצע שתי השנים שבדוח
    purchases_current_year: Optional[float] = None             # קניות סחורה ממאזן הבוחן (במקום עלות מכר)

    # ה. מבחנים משלימים (סימון ידני)
    concentration_test_met: bool = False               # B37 – 70% מגורם אחד ב-22 מתוך 36 חודשים
    officer_holds_under_25pct: bool = False            # B38 – (מידע; לא בנוסחאות)
    intercompany_dividend_received: float = 0.0        # B40
    holding_rate_in_paying_company: Optional[float] = None  # B41 – חובה להזין כשיש דיבידנד; ריק → סימון לבדיקה


# ---------------------------------------------------------------------------
# סימולטור – פרמטרים
# ---------------------------------------------------------------------------
@dataclass
class SimulatorParams:
    # החלטה 11: שיעור מס דיבידנד לכל לקוח. ברירת מחדל 33% (30% + מס יסף). יחיד מתחת לסף יסף – 30%;
    # בעל מניות שהוא חברה (126(ב)) – 0 כאן, והחישוב לפי תקנות הדיבידנדים ידני (מחוץ לתחולה).
    dividend_tax_rate: float = 0.33                    # סימולטור!B13
    surtax_rate: float = 0.02                          # חישוב_81!B26


# ---------------------------------------------------------------------------
# קלט לקוח שלם
# ---------------------------------------------------------------------------
@dataclass
class ClientInput:
    structure: CompanyStructure = field(default_factory=CompanyStructure)
    retained: RetainedEarningsInput = field(default_factory=RetainedEarningsInput)
    shields: ShieldsInput = field(default_factory=ShieldsInput)
    distributions: DistributionsInput = field(default_factory=DistributionsInput)
    s62a: Section62AInput = field(default_factory=Section62AInput)
    simulator: SimulatorParams = field(default_factory=SimulatorParams)
    flags: Flags = field(default_factory=Flags)
    data_as_of: str = ""                               # חותמת "נכון ל-" (תדריך, סעיף 10)
    is_estimate: bool = False                          # תרחיש ב׳ – נתונים מגלגול, לא מדוח סגור
    # החלטה 4: נתוני השנה הנבדקת הם מתחילת השנה עד חודש זה (1–12). ריק/12 = שנה מלאה.
    # המנוע מכפיל לינארית את תזרימי השנה (הכנסות, הכנסה חייבת, הוצאות). עד שיש מבנה אחיד – לינארי.
    data_through_month: Optional[int] = None
    # אברהם (סבב 2, 5–7): פירוט סעיפי הוצאה ממאזן הבוחן (שכר, עלויות מעסיק, שכירות, פחת, קבלני משנה, קניות…)
    # לבדיקת שלמות מול השנה הקודמת; חודשים בלי הכנסות
    period_breakdown: dict = field(default_factory=dict)
    period_breakdown_prev_year: dict = field(default_factory=dict)
    months_without_revenue: list = field(default_factory=list)
    # סבב 3 (אברהם): פירוט חודשי של הסעיפים ממאזן הבוחן – {סעיף: [12 חודשים]} – לאיתור חורים (חודש בלי שכר וכו׳)
    period_breakdown_months: dict = field(default_factory=dict)
    # תיקונים של רואה החשבון מעל הקבצים: [{"key","month","amount","kind","note","by","at","estimate"}]
    # kind: manual (סכום שהוזן) / accepted (אומדן שאושר) / dismissed (לא חסר – בלי אומדן). תיקון תמיד גובר על אומדן
    adjustments: list = field(default_factory=list)
    # סבב 4 (אברהם): כל שורות מאזן הבוחן של השנה (ושל השנה הקודמת – לעונתיות):
    # [{"id","code","name","section","group","income","kind","category","months":[12]}]
    # כשיש שורות – השנה מחושבת מסכום 12 התאים (קובץ / אומדן / תיקון), לא מהכפלה לינארית
    tb_rows: list = field(default_factory=list)
    tb_rows_prev_year: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClientInput":
        def build(klass, sub):
            sub = sub or {}
            unknown = set(sub) - set(klass.__dataclass_fields__)
            if unknown:
                raise ValueError(f"{klass.__name__}: שדות לא מוכרים: {sorted(unknown)}")
            return klass(**sub)

        return cls(
            structure=build(CompanyStructure, d.get("structure")),
            retained=build(RetainedEarningsInput, d.get("retained")),
            shields=build(ShieldsInput, d.get("shields")),
            distributions=build(DistributionsInput, d.get("distributions")),
            s62a=build(Section62AInput, d.get("s62a")),
            simulator=build(SimulatorParams, d.get("simulator")),
            flags=build(Flags, d.get("flags")),
            data_as_of=d.get("data_as_of", ""),
            is_estimate=bool(d.get("is_estimate", False)),
            data_through_month=d.get("data_through_month") or None,
            period_breakdown=dict(d.get("period_breakdown") or {}),
            period_breakdown_prev_year=dict(d.get("period_breakdown_prev_year") or {}),
            months_without_revenue=list(d.get("months_without_revenue") or []),
            period_breakdown_months={k: list(v) for k, v in (d.get("period_breakdown_months") or {}).items()},
            adjustments=[dict(a) for a in (d.get("adjustments") or [])],
            tb_rows=[dict(r) for r in (d.get("tb_rows") or [])],
            tb_rows_prev_year=[dict(r) for r in (d.get("tb_rows_prev_year") or [])],
        )
