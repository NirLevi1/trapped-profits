"""דוח לקוח בעברית (מרקדאון) – מקביל ללשונית «דאשבורד» + הסברים."""

from __future__ import annotations

from .engine import ClientResult


def _ils(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.0f} ₪"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _light(color: str) -> str:
    return {"ירוק": "🟢", "צהוב": "🟡", "אדום": "🔴"}.get(color, "")


def render_markdown(r: ClientResult) -> str:
    d, c, s, sim, sh, tr = r.dashboard, r.calc81, r.s62a, r.simulator, r.shields, r.transition
    lines: list[str] = []
    a = lines.append

    a(f"# {r.name} – ניטור רווחים כלואים, שנת המס {r.tax_year}")
    meta = [f"גרסת לוגיקה {r.logic_version}"]
    if r.data_as_of:
        meta.append(f"נכון ל־{r.data_as_of}")
    if r.is_estimate:
        meta.append("**אומדן (תרחיש ב׳)**")
    a(" · ".join(meta))
    a("")
    a(f"## {_light(d.color_overall)} סטטוס כולל: {d.status_overall}")
    a("")
    a("| מסלול | סטטוס |")
    a("| --- | --- |")
    a(f"| סעיף 81 – תוספת מס 2% | {_light(d.color_81)} {d.status_81} |")
    a(f"| סעיף 62א – רווחיות עודפת | {_light(d.color_62a)} {d.status_62a} |")
    a("")

    # --- 81 ---
    a("## מסלול 81 – תוספת מס 2%")
    a("")
    a("| נתון | ערך |")
    a("| --- | --- |")
    a(f"| רווחים נצברים לתום {r.previous_year} | {_ils(r.retained.retained_for_81a)} |")
    a(f"| החלופה המיטיבה | חלופה {c.chosen_alternative} |")
    a(f"| רווחים נצברים חייבים | {_ils(c.taxable_retained)} |")
    a(f"| המגן הקובע | {_ils(c.governing_shield)} (קבוע {_ils(sh.fixed_shield)}, הוצאות {_ils(sh.expenses_shield)}, נכסים {_ils(sh.assets_shield)}) |")
    if c.transition_reduction:
        a(f"| הפחתה לפי הוראות המעבר | {_ils(c.transition_reduction)} |")
    a(f"| רווחים עודפים | {_ils(c.excess_profits)} |")
    a(f"| קיים פטור? | {'כן' if c.is_exempt else 'לא'} |")
    a(f"| **תוספת מס לתשלום** | **{_ils(c.surtax)}** |")
    a(f"| הגנת הוראת מעבר עד שנת | {d.protected_until} |")
    a("")
    exempt_bits = []
    if c.exempt_losses:
        exempt_bits.append("הפסדי השנה מעל 10% מהרווחים הנצברים")
    if c.exempt_50pct:
        exempt_bits.append("דיבידנד ≥ 50% מהרווחים העודפים")
    if c.exempt_6pct:
        exempt_bits.append(f"דיבידנד ≥ {_pct(c.required_distribution_rate)} מהרווחים הנצברים")
    if c.exempt_transition_2025:
        exempt_bits.append("הוראת מעבר 2025 – חלוקה בתקופה הקובעת")
    if exempt_bits:
        a("מבחני פטור שהתקיימו: " + "; ".join(exempt_bits) + ".")
        a("")

    # --- simulator ---
    a("## סימולטור – לחלק דיבידנד או לשלם 2%?")
    a("")
    if not sim.action_required:
        a(f"**{sim.recommendation}.** הסכומים להלן הם לידיעה בלבד.")
        a("")
    a("| חלופה | סכום |")
    a("| --- | --- |")
    a(f"| {_pct(c.required_distribution_rate)} מהרווחים הנצברים | {_ils(sim.option_6pct)} |")
    a(f"| 50% מהרווחים העודפים לתום {r.previous_year} | {_ils(sim.option_50pct)} |")
    if sim.option_20pct_start_day is not None:
        a(f"| 20% מהרווחים שנותרו מיום התחילה (הוראת מעבר) | {_ils(sim.option_20pct_start_day)} |")
    a(f"| **דיבידנד מינימלי לפטור** ({sim.cheaper_option}) | **{_ils(sim.min_dividend)}** |")
    a(f"| כבר חולק השנה | {_ils(sim.already_distributed)} |")
    gap = f"**{_ils(sim.gap_to_close)}**" if sim.action_required else "לא נדרש"
    a(f"| **פער לסגירה עד 31.12** | {gap} |")
    a(f"| מס דיבידנד על הפער | {_ils(sim.dividend_tax_cost)} |")
    a(f"| תוספת המס אם לא מחלקים | {_ils(sim.surtax_if_not_distributing)} |")
    if sim.years_to_breakeven:
        a(f"| שנים לאיזון | {sim.years_to_breakeven:.1f} |")
    if sim.estimated_retained_year_end is not None:
        a(f"| אומדן עודפים ל־31.12.{r.tax_year} (תצוגה) | {_ils(sim.estimated_retained_year_end)} |")
    a("")
    if sim.surtax_if_salary_paid is not None and sim.surtax_if_salary_paid < c.surtax:
        a(f"| תוספת המס אם משלמים את שכר 62א עד 31.12 | {_ils(sim.surtax_if_salary_paid)} |")
    a("")
    a(f"**המלצה:** {sim.recommendation_text or sim.recommendation}")
    a("")

    # --- 62a ---
    a("## מסלול 62א – רווחיות עודפת")
    a("")
    a("| נתון | ערך |")
    a("| --- | --- |")
    a(f"| הכנסה מפעילות עתירת יגיעה אישית | {_ils(s.personal_effort_income)} |")
    a(f"| הכנסה חייבת מפעילות זו | {_ils(s.taxable_income_personal_effort)} |")
    a(f"| שיעור רווחיות | {_pct(s.governing_profitability)} |")
    a(f"| חצה סף 25%? | {'כן' if s.crossed_25pct else 'לא'} |")
    a(f"| מתחת לסף המחזור ({_ils(s.revenue_threshold)})? | {'כן' if s.below_revenue_threshold else 'לא'} |")
    a(f"| פטור 750 אלף (אין שליטה בחברה אחרת)? | {'חל' if s.exemption_750k_applies else 'לא חל'} |")
    a(f"| הסעיף חל? | {'כן' if s.section_applies else 'לא'} |")
    a(f"| **הכנסה מיוחסת = שכר לתיקון עד 31.12** | **{_ils(s.attributed_income)}** |")
    a(f"| עלות מס נוספת מוערכת | {_ils(s.extra_tax_cost)} |")
    a("")

    # --- manual review ---
    if r.manual_review:
        a("## לבדיקה ידנית")
        a("")
        for m in r.manual_review:
            a(f"- {m}")
        a("")

    a("---")
    a("*כלי ניטור וסינון ראשוני בלבד – אינו תחליף לחישוב שומתי מלא. "
      "ספרים שוטפים אינם סגורים; כל נתון שנגזר מהם הוא אומדן.*")
    return "\n".join(lines)
