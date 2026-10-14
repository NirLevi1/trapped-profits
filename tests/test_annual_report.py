"""קריאת הדוח השנתי: PDF דיגיטלי קטן באותו מבנה (מאזן + רווח והפסד, שתי עמודות שנים), וניתוב החריצים."""
import tempfile
from pathlib import Path

import pytest

from trapped_profits.annual_report import group_lines, _label, _numbers, Word, parse_annual_report
from trapped_profits.importers import import_slot, SLOTS


def _pdf() -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf"):
        if Path(cand).exists():
            font = cand
            break
    if not font:
        pytest.skip("אין גופן עברי לבדיקה")
    def page(lines):
        pg = doc.new_page()
        y = 60
        for row in lines:
            # row: (label, col2024, col2025) – התווית מימין, 2025 במרכז, 2024 משמאל (כמו בדוח)
            lab, a, b = row
            if lab:
                pg.insert_text((400, y), lab[::-1] if False else lab, fontsize=10, fontname="heb", fontfile=font)
            if b is not None:
                pg.insert_text((260, y), b, fontsize=10, fontname="heb", fontfile=font)
            if a is not None:
                pg.insert_text((120, y), a, fontsize=10, fontname="heb", fontfile=font)
            y += 18
    page([("חברת בדיקה בע\"מ", None, None), ("דוחות כספיים", None, None), ("ליום 31 בדצמבר", "2024", "2025")])
    page([("חברת בדיקה בע\"מ", None, None), ("מאזן", None, None), ("ליום 31 בדצמבר", "2024", "2025"),
          ("מזומנים ושווי מזומנים", "2,000", "70,000"), ("לקוחות", "100,000", "120,000"),
          ("הון מניות", "100", "100"), ("פרמיה", "900", "900"), ("רווח (הפסד) שנצבר", "378,051", "382,730")])
    page([("חברת בדיקה בע\"מ", None, None), ("דוח רווח והפסד", None, None), ("לשנה שהסתיימה ביום 31 בדצמבר", "2024", "2025"),
          ("הכנסות ממתן שירותים", "1,441,530", "2,102,725"), ("הוצאות הנהלה וכלליות", "1,088,077", "2,064,288"),
          ("הוצאות מימון", "694", "9,375"), ("רווח לאחר הוצאות מימון", "352,759", "30,168"),
          ("ייעוד רווחים", "200,000", "35,000")])
    p = Path(tempfile.mkdtemp()) / "report.pdf"
    doc.save(str(p))
    return p


def test_line_grouping_and_rtl_label():
    ws = [Word(300, 10, 340, 20, "מניות"), Word(345, 10, 360, 20, "הון"), Word(100, 11, 130, 21, "101"), Word(200, 9, 230, 19, "5")]
    lines = group_lines(ws)
    assert len(lines) == 1 and _label(lines[0]) == "הון מניות"
    assert [v for _, v in _numbers(lines[0])] == [101.0]          # "5" = מספר באור, נזרק


def test_parse_digital_pdf():
    r = parse_annual_report(_pdf())
    f = r["fields"]
    assert f["structure.last_closed_report_year"] == 2025
    assert f["retained.balance_sheet_retained_earnings"] == 382_730 and f["distributions.retained_at_start_day"] == 378_051
    assert f["shields.share_capital_and_premium"] == 1_000 and f["shields.special_loans_deposits_cash"] == 70_000
    assert f["shields.expenses_prev_year"] == 2_064_288 + 9_375 and f["shields.expenses_prev2_year"] == 1_088_077 + 694
    assert f["distributions.dividend_in_determining_period"] == 35_000
    assert "בע" in f["structure.name"]
    assert all(k in r["sources"] for k in ("retained.balance_sheet_retained_earnings", "shields.expenses_prev_year"))


def test_slot_routing_rejects_wrong_kind():
    assert set(SLOTS) == {"annual_report", "trial_balance", "ledger"}
    bad = Path(tempfile.mkdtemp()) / "x.csv"
    bad.write_text("שלום", encoding="utf-16")
    with pytest.raises(ValueError):
        import_slot("trial_balance", bad)
    with pytest.raises(ValueError):
        import_slot("annual_report", bad)
