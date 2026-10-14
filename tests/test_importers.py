"""ייבוא מריווחית: מאזן בוחן לפי חודשים + כרטסת הכנסות (קבצים סינתטיים באותו מבנה, UTF-16 עם טאבים)."""
import tempfile
from pathlib import Path

from trapped_profits.importers import detect, import_files, parse_ledger, parse_trial_balance

Q = '"'


def _w(name: str, lines: list[str]) -> Path:
    p = Path(tempfile.mkdtemp()) / name
    p.write_text("\r\n".join(lines), encoding="utf-16")
    return p


def _tb():
    # סדר העמודות כמו בייצוא: סה"כ, דצמבר..ינואר, יתרת פתיחה, שם
    def row(total, by_month, name):   # by_month: ינואר..דצמבר
        cols = [total] + by_month[::-1] + ["0.00", name]
        return "\t".join(cols)
    return _w("tb.CSV", [
        "תאריך - 14/10/26", "", "יצוא דוח\t\t\t\t\t\tדוח מאזן בוחן יתרות - לפי חודשים ", "", "\t\t\t\t\tמחודש 1/2026 עד חודש 12/2026",
        "רווח והפסד", "הכנסות", "הכנסות ממכירות ומתן שירותים",
        "סה\"כ יתרה\tדצמבר\tנובמבר\tאוקטובר\tספטמבר\tאוגוסט\tיולי\tיוני\tמאי\tאפריל\tמרץ\tפברואר\tינואר\tיתרת פתיחה\t כרטיס חשבון",
        "מכירות סחורה - 70",
        row("(300,000.00)", ["(100,000.00)", "(100,000.00)", "(100,000.00)"] + ["0.00"] * 9, "4 הכנסות/מכירות"),
        row("(300,000.00)", ["(100,000.00)"] * 3 + ["0.00"] * 9, "סה''כ: מכירות סחורה - 70"),
        "הכנסות מימון",
        row("(1,000.00)", ["(1,000.00)"] + ["0.00"] * 11, "90 ריבית שהתקבלה"),
        "עלויות ייצור", "הוצאות הפעלה - 80",
        row("60,000.00", ["20,000.00"] * 3 + ["0.00"] * 9, "17 עבודות חוץ"),
        row("30,000.00", ["10,000.00"] * 3 + ["0.00"] * 9, "35 שכר עבודה"),
        row("12,000.00", ["0.00"] * 11 + ["12,000.00"], "40 פחת"),
        row("9,000.00", ["3,000.00"] * 3 + ["0.00"] * 9, "41 דמי ניהול"),
        row("111,000.00", ["33,000.00"] * 3 + ["0.00"] * 8 + ["12,000.00"], "סה''כ: עלויות ייצור"),
        row("(190,000.00)", ["(67,000.00)"] * 3 + ["0.00"] * 9, "סה''כ רווח בדוח רווח והפסד"),
    ])


def _ledger():
    h = "\t".join([Q + x + Q for x in ["פרטים", "(פקודה) חודש/שנה", "אסמכתא 2", "אסמכתא 1", "תאריך ערך", "תאריך אסמכתא", "יתרה", "זכות", "חובה", "חשבון נגדי"]])
    def r(name, credit, debit="0.00"):
        return "\t".join([Q + x + Q for x in [name, "(1) 1/26", "1", "5001", "05/01/26", "05/01/26", "0.00", credit, debit, name + "  84"]])
    return _w("ledger.csv", ["", Q + "דוח כרטסת הנהלת חשבונות" + Q, "", h,
                             r("לקוח א", "70,000.00"), r("לקוח ב", "20,000.00"), r("לקוח א", "(10,000.00)"), r("לקוח ג", "20,000.00")])


def test_detect_and_trial_balance():
    p = _tb()
    assert detect(p) == "trial_balance"
    r = parse_trial_balance(p)
    f, s = r["fields"], r["summary"]
    assert s["revenue"] == 300_000 and s["fin_income"] == 1_000 and s["expenses"] == 111_000
    assert abs(s["profit"] - 190_000) < 1e-6
    assert f["s62a.total_revenue"] == 300_000 and f["s62a.other_interest"] == 1_000
    assert f["shields.expenses_current_year"] == 99_000            # בלי פחת
    assert f["data_through_month"] == 3 and f["structure.tax_year"] == 2026
    assert r["hints"]["salaries"] == 30_000 and r["hints"]["management_fees"] == 9_000
    assert any("דמי ניהול" in n for n in r["notes"])


def test_ledger_by_customer():
    p = _ledger()
    assert detect(p) == "ledger"
    r = parse_ledger(p)
    tc = r["fields"]["s62a.top_customers"]
    assert tc[0] == {"name": "לקוח א", "amount": 60_000.0} and len(tc) == 3
    assert abs(r["summary"]["top_share"] - 0.6) < 1e-9


def test_import_files_merges_and_reports_unknown():
    bad = _w("x.csv", ["שלום"])
    r = import_files([_tb(), _ledger(), bad])
    assert "s62a.top_customers" in r["fields"] and "s62a.total_revenue" in r["fields"]
    assert len(r["files"]) == 2 and len(r["errors"]) == 1
