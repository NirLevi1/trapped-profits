"""קריאת קלט לקוח מקובץ האקסל המקורי (התאים הצהובים), ומיפוי תאי הפלט לתוצאות המנוע.

משמש לבדיקות הזהב מול האקסל, וגם ככלי ייבוא ללקוח שמולא ידנית באקסל.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from .models import (
    ClientInput, CompanyStructure, RetainedEarningsInput, ShieldsInput,
    DistributionsInput, Section62AInput, SimulatorParams, Flags,
)


def _yes(v: Any) -> bool:
    return str(v).strip() == "כן"


def _num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    return float(v)


def load_client_from_excel(path: str | Path, flags: Flags | None = None) -> ClientInput:
    wb = openpyxl.load_workbook(path, data_only=True)
    m, r, g, d, s, sim = (wb["מבנה"], wb["רווחים_נצברים"], wb["מגנים"],
                          wb["חלוקות"], wb["סעיף_62א"], wb["סימולטור"])
    v = lambda ws, c: ws[c].value  # noqa: E731

    structure = CompanyStructure(
        name=str(v(m, "B5") or ""), company_id=str(v(m, "B6") or ""),
        tax_year=int(v(m, "B7")),
        is_few_holders_company=_yes(v(m, "B11")),
        preferred_or_approved_enterprise=_yes(v(m, "B12")),
        controlling_owners_count=int(_num(v(m, "B17")) or 1),
        group_companies_count=int(_num(v(m, "B18")) or 1),
        group_companies_waived=int(_num(v(m, "B19"))),
        has_material_holder=_yes(v(m, "B22")),
        material_holder_total_profits=_num(v(m, "B23")),
        owner_controls_another_company=_yes(v(m, "B24")),
        partnership_income_share=_num(v(m, "B27")),
        encouragement_law_status=str(v(m, "B28") or "אין"),
    )
    b5 = v(r, "B5")
    retained = RetainedEarningsInput(
        cumulative_taxable_income=None if (b5 in (None, "", 0)) else float(b5),
        cumulative_exempt_income=_num(v(r, "B6")), cumulative_land_appreciation=_num(v(r, "B7")),
        cumulative_tax=_num(v(r, "B8")), cumulative_dividends=_num(v(r, "B9")),
        uncredited_loss=_num(v(r, "B10")),
        balance_sheet_retained_earnings=_num(v(r, "B14")), capitalized_profits=_num(v(r, "B15")),
        transparent_entity_profits=_num(v(r, "B16")), attributed_to_shareholders=_num(v(r, "B20")),
        exempt_preferred_enterprise_income=_num(v(r, "B24")), exempt_industrial_sales_income=_num(v(r, "B25")),
        exempt_building_8a_income=_num(v(r, "B26")), exempt_financial_institution_income=_num(v(r, "B27")),
        exempt_profits_last_7_years=_num(v(r, "B33")),
    )
    shields = ShieldsInput(
        fixed_shield_base=_num(v(g, "B5")),
        expenses_current_year=_num(v(g, "B10")), expenses_prev_year=_num(v(g, "B11")),
        expenses_prev2_year=_num(v(g, "B12")), pay_62a_salary_by_year_end=_yes(v(g, "B15")),
        total_assets_cost=_num(v(g, "B17")),
        special_securities=_num(v(g, "B20")), special_financial_asset=_num(v(g, "B21")),
        special_intangible_royalty=_num(v(g, "B22")), special_real_estate=_num(v(g, "B23")),
        special_loans_deposits_cash=_num(v(g, "B24")),
        excl_own_use_real_estate=_num(v(g, "B27")), excl_rental_building=_num(v(g, "B28")),
        excl_pledged_cash_financing=_num(v(g, "B29")), excl_regulatory_equity_cash=_num(v(g, "B30")),
        share_capital_and_premium=_num(v(g, "B33")), related_party_loan=_num(v(g, "B34")),
        held_company_cost=_num(v(g, "B35")),
    )
    distributions = DistributionsInput(
        dividends_taxed_current_year=_num(v(d, "B4")), losses_current_year=_num(v(d, "B5")),
        excess_profits_prev_year=_num(v(d, "B9")),
        start_day_excess_profits=_num(v(d, "B12")), start_day_dividends_taxed=_num(v(d, "B13")),
        retained_at_start_day=_num(v(d, "B18")), dividend_in_determining_period=_num(v(d, "B19")),
        determining_period_paid_and_taxed=_yes(v(d, "B20")),
    )
    s62a = Section62AInput(
        total_revenue=_num(v(s, "B4")),
        other_interest=_num(v(s, "B6")), other_dividend=_num(v(s, "B7")), other_rent=_num(v(s, "B8")),
        other_asset_sale=_num(v(s, "B9")), other_securities_inventory_sale=_num(v(s, "B10")),
        other_real_estate_sale=_num(v(s, "B11")),
        taxable_income_personal_effort=_num(v(s, "B16")), related_company_payments=_num(v(s, "B17")),
        avg_profitability_2023_2025=_num(v(s, "B19")),
        marginal_tax_rate=_num(v(s, "B32")), corporate_tax_rate=_num(v(s, "B33")),
        concentration_test_met=_yes(v(s, "B37")), officer_holds_under_25pct=_yes(v(s, "B38")),
        intercompany_dividend_received=_num(v(s, "B40")),
        holding_rate_in_paying_company=None if v(s, "B41") in (None, "") else float(v(s, "B41")),
    )
    simulator = SimulatorParams(
        dividend_tax_rate=_num(v(sim, "B13")),
        surtax_rate=_num(v(wb["חישוב_81"], "B26")),
    )
    return ClientInput(structure=structure, retained=retained, shields=shields,
                       distributions=distributions, s62a=s62a, simulator=simulator,
                       flags=flags or Flags())


def excel_flags() -> Flags:
    """דגלים שמשחזרים בדיוק את התנהגות האקסל (לבדיקות הזהב)."""
    return Flags(deduct_transition_from_50pct_base=True, enable_20pct_current_year_rule=True,
                 deduction_base_excludes_related_payments=True)


def _yn(b: bool) -> str:
    return "כן" if b else "לא"


def result_as_excel_cells(res) -> dict[str, Any]:
    """מיפוי תוצאות המנוע → תאי הנוסחאות באקסל. משמש להשוואה תא-תא."""
    st_prev = res.previous_year
    r, g, d, s, c, sim, db = (res.retained, res.shields, res.transition, res.s62a,
                              res.calc81, res.simulator, res.dashboard)
    cells: dict[str, Any] = {
        "מבנה!B8": st_prev,
        "מבנה!B13": _yn(res.applies_81),
        "מבנה!B14": _yn(res.applies_62a),
        "מבנה!B20": res.companies_for_750k_split,
        "מגנים!B6": res.companies_for_750k_split,
        "רווחים_נצברים!B11": r.formula_profits,
        "רווחים_נצברים!B17": r.accounting_cap,
        "רווחים_נצברים!B19": r.retained_profits,
        "רווחים_נצברים!B21": r.retained_for_81a,
        "רווחים_נצברים!B28": r.exempt_sources_total,
        "רווחים_נצברים!B29": r.special_assets_net,
        "רווחים_נצברים!B30": r.exempt_alt1,
        "רווחים_נצברים!B37": r.taxable_retained_alt1,
        "רווחים_נצברים!B38": r.taxable_retained_alt2,
        "מגנים!B7": g.fixed_shield,
        "מגנים!B13": g.expenses_avg_3y,
        "מגנים!B14": g.expenses_shield,
        "מגנים!B25": g.special_assets_gross,
        "מגנים!B31": g.special_assets_net,
        "מגנים!B36": g.assets_shield,
        "מגנים!B39": g.governing_shield_alt1,
        "מגנים!B40": g.governing_shield_alt2,
        "חלוקות!B8": r.retained_for_81a,
        "חלוקות!B14": d.start_day_remaining,
        "חלוקות!B15": _yn(d.rule_20pct_met),
        "חלוקות!B21": d.determining_period_rate,
        "חלוקות!B22": d.protected_until_year,
        "חלוקות!B23": _yn(d.protected_in_tax_year),
        "סעיף_62א!B12": s.other_income_total,
        "סעיף_62א!B13": s.personal_effort_income,
        "סעיף_62א!B18": s.profitability,
        "סעיף_62א!B20": s.governing_profitability,
        "סעיף_62א!B21": _yn(s.crossed_25pct),
        "סעיף_62א!B24": s.revenue_threshold,
        "סעיף_62א!B25": "כן – הסעיף עשוי לחול" if s.below_revenue_threshold else "לא – הסעיף אינו חל",
        "סעיף_62א!B26": "חל פטור" if s.exemption_750k_applies else "לא חל",
        "סעיף_62א!B27": _yn(s.section_applies),
        "סעיף_62א!B30": s.deduction_25pct,
        "סעיף_62א!B31": s.attributed_income,
        "סעיף_62א!B34": s.extra_tax_cost,
        "סעיף_62א!B39": "כן – 55% ייוחסו" if s.partnership_under_10pct else "לא",
        "סעיף_62א!B42": s.intercompany_dividend_attributed,
        "חישוב_81!B4": c.transition_reduction,
        "חישוב_81!B5": c.excess_alt1,
        "חישוב_81!B6": c.excess_alt2,
        "חישוב_81!B7": f"חלופה {c.chosen_alternative}",
        "חישוב_81!B8": c.taxable_retained,
        "חישוב_81!B9": c.governing_shield,
        "חישוב_81!B10": c.excess_profits,
        "חישוב_81!B13": c.dividend_deducted,
        "חישוב_81!B14": c.surtax_base,
        "חישוב_81!B17": c.required_distribution_rate,
        "חישוב_81!B18": "פטור" if c.exempt_losses else "לא",
        "חישוב_81!B19": "פטור" if c.exempt_50pct else "לא",
        "חישוב_81!B20": "פטור" if c.exempt_6pct else "לא",
        "חישוב_81!B21": "פטור" if c.exempt_transition_2025 else "לא",
        "חישוב_81!B23": _yn(c.is_exempt),
        "חישוב_81!B27": c.surtax,
        "סימולטור!B5": sim.option_6pct,
        "סימולטור!B6": sim.option_50pct,
        "סימולטור!B7": sim.cheaper_option,
        "סימולטור!B8": sim.min_dividend,
        "סימולטור!B9": sim.already_distributed,
        "סימולטור!B10": sim.gap_to_close,
        "סימולטור!B14": sim.dividend_tax_cost,
        "סימולטור!B15": sim.surtax_if_not_distributing,
        "סימולטור!B16": sim.difference,
        "סימולטור!B17": sim.years_to_breakeven,
        "סימולטור!B20": sim.recommendation,
        "דאשבורד!B3": res.name,
        "דאשבורד!B4": res.tax_year,
        "דאשבורד!B7": r.retained_for_81a,
        "דאשבורד!B8": f"חלופה {c.chosen_alternative}",
        "דאשבורד!B9": c.taxable_retained,
        "דאשבורד!B10": c.governing_shield,
        "דאשבורד!B11": c.excess_profits,
        "דאשבורד!B12": _yn(c.is_exempt),
        "דאשבורד!B13": c.surtax,
        "דאשבורד!B14": sim.min_dividend,
        "דאשבורד!B15": sim.gap_to_close,
        "דאשבורד!B16": db.protected_until if db.protected_until == "אין" else int(db.protected_until),
        "דאשבורד!B18": s.governing_profitability,
        "דאשבורד!B19": _yn(s.crossed_25pct),
        "דאשבורד!B20": _yn(s.section_applies),
        "דאשבורד!B21": s.attributed_income,
        "דאשבורד!B22": s.extra_tax_cost,
        "דאשבורד!B25": db.status_81,
        "דאשבורד!B26": db.status_62a,
        "דאשבורד!B27": db.status_overall,
    }
    return cells
