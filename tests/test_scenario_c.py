"""תרחיש ג׳ (15.10): הדוח הסגור האחרון ישן בשנתיים (2023 לשנת מס 2026) – גלגול שנתיים ממאזני בוחן מלאים."""
import json
from pathlib import Path

from trapped_profits.models import ClientInput
from trapped_profits.engine import compute, _roll_lag, _rolled_retained, _rolled_start_day
from trapped_profits.annual_report import map_annual_fields
from trapped_profits import store as S


def _client(last_closed=2023):
    d = json.loads(Path("examples/clients/" + sorted(p.name for p in Path("examples/clients").glob("*.json"))[0]).read_text(encoding="utf-8"))
    d["structure"]["tax_year"] = 2026
    d["structure"]["last_closed_report_year"] = last_closed
    d["retained"]["balance_sheet_retained_earnings"] = 1_000_000
    d["retained"]["cumulative_taxable_income"] = None
    d["retained"]["prev2_year_profit_for_rollover"] = 500_000      # 2024
    d["retained"]["prev_year_profit_for_rollover"] = 400_000       # 2025
    d["distributions"]["dividends_prev2_year"] = 100_000
    d["distributions"]["dividends_prev_year"] = 50_000
    d["distributions"]["retained_at_start_day"] = 0
    return d


def test_two_year_roll():
    ci = ClientInput.from_dict(_client())
    assert _roll_lag(ci) == 2
    end24 = 1_000_000 + 500_000 * 0.77 - 100_000
    assert abs(_rolled_start_day(ci) - end24) < 1
    assert abs(_rolled_retained(ci) - (end24 + 400_000 * 0.77 - 50_000)) < 1
    r = compute(ci).to_dict()
    assert r["scenario_label"].startswith("אומדן (תרחיש ג׳")
    assert "תרחיש ג׳" in r["retained"]["rollover_note"] and "2024" in r["retained"]["rollover_note"]
    assert any("תרחיש ג׳" in x and "יום התחילה" in x for x in r["manual_review"])


def test_start_day_used_for_transition_when_missing():
    d = _client()
    d["distributions"]["dividend_in_determining_period"] = 900_000
    d["distributions"]["determining_period_paid_and_taxed"] = True
    r = compute(ClientInput.from_dict(d)).to_dict()
    end24 = 1_000_000 + 500_000 * 0.77 - 100_000
    assert abs(r["transition"]["determining_period_rate"] - 900_000 / end24) < 1e-6


def test_scenario_b_unchanged_and_missing_profit_stops_roll():
    ci = ClientInput.from_dict(_client(2024))
    assert _roll_lag(ci) == 1
    assert abs(_rolled_retained(ci) - (1_000_000 + 400_000 * 0.77 - 50_000)) < 1      # prev2 ignored in B
    d = _client()
    d["retained"]["prev2_year_profit_for_rollover"] = None
    r = compute(ClientInput.from_dict(d)).to_dict()
    assert any("חסר רווח 2024" in x for x in r["manual_review"])


def test_annual_mapping_gap3_note():
    notes = []
    f, _ = map_annual_fields({"retained": {"2023": 900_000, "2022": 700_000}, "expenses": {"2023": 1, "2022": 2}}, 2023, 2026, {}, notes)
    assert f["retained.balance_sheet_retained_earnings"] == 900_000 and "distributions.retained_at_start_day" not in f
    assert "shields.expenses_prev_year" not in f and "shields.expenses_prev2_year" not in f
    assert any("תרחיש ג׳" in n for n in notes)


def test_rollover_after_scenario_c_rolls_one_year(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(S, "data_root", lambda: root)
    st = S.ClientStore()
    rec = st.save(_client(), None)
    rolled = rec["result"]["retained"]["retained_for_81a"]
    new = st.rollover_year(rec["id"])
    inp = new["input"]
    assert inp["structure"]["tax_year"] == 2027 and inp["retained"]["retained_as_of_year"] == 2025
    assert inp["retained"]["prev2_year_profit_for_rollover"] is None
    ci = ClientInput.from_dict(inp)
    assert _roll_lag(ci) == 1


def test_gross_margin_not_from_cost_line(tmp_path):
    """15.10: "עלות המכירות" הכילה את המילה "מכירות" ונלקחה כהכנסות → 10,701%. עכשיו מכירות = רווח גולמי + עלות המכר; אחוז מעל 100% נפסל."""
    import pytest
    pdf = Path("/tmp/claude-0/-home-claude/b7636fe5-5021-5400-a5d6-dd52a8b2ec43/scratchpad/rep24/r.pdf")
    if not pdf.exists():
        pytest.skip("קובץ הלקוח לא זמין בסביבה הזו")
    from trapped_profits.annual_report import parse_annual_report
    h = parse_annual_report(pdf)["fields"]["s62a.gross_profit_history"]
    assert [round(x["rate"], 3) for x in h] == [0.991, 0.972]


def test_glyph_nun_font_and_name_vote():
    """17.10: PDF שבו "נ" מקודדת כ-ð – המאזן לא זוהה והשם יצא 'בע"מ'. עכשיו: בונים מילים מהאותיות; השם – הנפוץ בעמודים."""
    import pytest
    pdf = Path("/tmp/claude-0/-home-claude/b7636fe5-5021-5400-a5d6-dd52a8b2ec43/scratchpad/rep24/r.pdf")
    if not pdf.exists():
        pytest.skip("קובץ הלקוח לא זמין בסביבה הזו")
    from trapped_profits.annual_report import parse_annual_report
    f = parse_annual_report(pdf)["fields"]
    assert f["structure.name"] == 'א. לודריק פיקוח וניהול פרויקטיים בע"מ'
    assert f["retained.balance_sheet_retained_earnings"] == 467072 and f["shields.share_capital_and_premium"] == 1001
