"""בדיקות זהב: כל תא נוסחה באקסל (25 תרחישים × 89 תאים) מול המנוע.

הערך הצפוי חושב על-ידי ליברה-אופיס מהאקסל המקורי (golden/make_golden.py).
הסטיות המכוונות מהאקסל מתועדות ב-DEVIATIONS למטה ונבדקות בנפרד ב-test_deviations_*.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from trapped_profits import compute
from trapped_profits.excel_io import load_client_from_excel, excel_flags, result_as_excel_cells

ROOT = Path(__file__).parent.parent
CASES = sorted((ROOT / "golden" / "cases").iterdir())


# סטיות מכוונות מהאקסל (README, "באגים ידועים באקסל" ו"סטיות מכוונות"):
#  א. סימולטור!B20 – שלושה באגים בנוסחה (הפניות לתאים ריקים, השוואה שגויה). הקוד מחשב אחרת.
#  ב. חישוב_81!B7/B9, דאשבורד!B8/B10 – בשוויון בין החלופות האקסל בוחר חלופה 1 (ומאבד את מגן
#     הנכסים); הסיכום: חברה בלי רווחים פטורים – תמיד חלופה 2.
#  ג. דאשבורד!B25/B27 – לקוח פטור (למשל לפי מבחן ההפסדים) מקבל באקסל "צהוב – נדרשת חלוקה".
#  ה. דאשבורד!B26 – רווחיות מעל 25% עם פטור 750 אלף: באקסל "מתקרבת לסף 25%" (מטעה); אצלנו אותו צבע, ניסוח "פטור: עודפים עד 750 אלף" (17.10)
#  ד. סימולטור!B7/B8/B10/B14/B16/B17, דאשבורד!B14/B15 – כשבסיס ה-50% הוא 0 האקסל נותן דיבידנד מינימלי 0.
def _skip_cell(ref: str, res) -> bool:
    sheet_cell = ref
    if sheet_cell == "סימולטור!B20":
        return True
    tie = res.calc81.excess_alt1 == res.calc81.excess_alt2 and res.retained.exempt_sources_total <= 0
    if tie and sheet_cell in ("חישוב_81!B7", "חישוב_81!B9", "דאשבורד!B8", "דאשבורד!B10"):
        return True
    if res.calc81.is_exempt and sheet_cell in ("דאשבורד!B25", "דאשבורד!B27"):
        return True
    if sheet_cell == "דאשבורד!B26" and res.s62a.crossed_25pct and res.s62a.exemption_750k_applies:
        return res.dashboard.status_62a.startswith("צהוב – פטור: עודפים עד 750 אלף")
    if res.simulator.option_50pct <= 0 and sheet_cell in (
        "סימולטור!B7", "סימולטור!B8", "סימולטור!B10", "סימולטור!B14", "סימולטור!B16", "סימולטור!B17",
        "דאשבורד!B14", "דאשבורד!B15",
    ):
        return True
    return False


def _close(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    if a is None or b is None:
        return a == b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)


@pytest.mark.parametrize("case_dir", CASES, ids=[c.name for c in CASES])
def test_matches_excel(case_dir: Path) -> None:
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    ci = load_client_from_excel(case_dir / "input.xlsx", flags=excel_flags())
    res = compute(ci)
    got = result_as_excel_cells(res)

    missing = sorted(set(expected) - set(got))
    assert not missing, f"תאים ללא מיפוי במנוע: {missing}"

    diffs, skipped = [], 0
    for ref, exp in expected.items():
        if _skip_cell(ref, res):
            skipped += 1
            continue
        if not _close(exp, got[ref]):
            diffs.append(f"{ref}: אקסל={exp!r} מנוע={got[ref]!r}")
    assert not diffs, "\n".join(diffs)
    assert skipped <= 12, f"יותר מדי תאים דולגו ({skipped}) – לבדוק את כללי הדילוג"


def _res(case: str):
    d = ROOT / "golden" / "cases" / case
    excel = json.loads((d / "expected.json").read_text(encoding="utf-8"))
    return compute(load_client_from_excel(d / "input.xlsx", flags=excel_flags())), excel


@pytest.mark.parametrize("case,expected_text", [
    ("no_few_holders", "החוק אינו חל – אין פעולה נדרשת"),
    ("dividend_meets_6pct", "עומדת בפטור – אין פעולה נדרשת"),
    ("dividend_meets_50pct", "עומדת בפטור – אין פעולה נדרשת"),
    ("losses_exempt", "עומדת בפטור – אין פעולה נדרשת"),
    ("base", "תוספת המס זולה יותר השנה – יש לבחון את ההשפעה הרב-שנתית"),   # 141,867 > 57,300
])
def test_deviations_recommendation(case: str, expected_text: str) -> None:
    res, _ = _res(case)
    assert res.simulator.recommendation == expected_text


def test_deviations_recommendation_prefers_distribution_when_cheaper() -> None:
    """מס הדיבידנד על הפער קטן מתוספת המס → המלצה לחלק (באקסל ההשוואה הייתה מול תא ריק)."""
    res, _ = _res("base")
    ci = load_client_from_excel(ROOT / "golden" / "cases" / "base" / "input.xlsx", flags=excel_flags())
    ci.distributions.dividends_taxed_current_year = 300_000   # פער 129,900 → מס 42,867 < תוספת 51,300
    r = compute(ci)
    assert r.simulator.dividend_tax_cost < r.calc81.surtax
    assert r.simulator.recommendation.startswith("מומלץ לשקול חלוקה")


def test_deviations_tie_prefers_alternative_2() -> None:
    res, excel = _res("assets_shield_small")
    assert excel["חישוב_81!B7"] == "חלופה 1"
    assert res.calc81.chosen_alternative == 2
    assert res.calc81.excess_profits == excel["חישוב_81!B10"]   # הסכום זהה, רק התיוג שונה


def test_deviations_exempt_is_not_yellow() -> None:
    res, excel = _res("losses_exempt")
    assert excel["דאשבורד!B25"].startswith("צהוב")
    assert res.dashboard.status_81 == "ירוק – מוגן"
    assert res.simulator.action_required is False
