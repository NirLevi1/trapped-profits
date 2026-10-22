"""סבב 4 (אברהם 15.10): מאזן הבוחן המלא – טבלה חודשית, אומדן לחודשים שטרם הוזנו, עריכה שמשפיעה על החישוב, החלפה בקובץ הבא."""
import json
from pathlib import Path

from trapped_profits.models import ClientInput
from trapped_profits.engine import compute
from trapped_profits import store as S


def _row(id_, name, months, income=False, kind="expense", category=None, section="הוצאות", group=""):
    return {"id": id_, "code": id_, "name": name, "section": section, "group": group, "income": income, "kind": kind, "category": category, "months": months}


def _base():
    d = json.loads(Path("examples/clients/חברה ו – מלאי, נתונים עד אוגוסט.json").read_text(encoding="utf-8"))
    d["s62a"]["has_inventory"] = False
    d["data_through_month"] = 6
    # הכנסות 100 אלף לחודש בזכות (שלילי בקובץ), שכר 10 אלף, שכירות 2 אלף עם חור במאי
    d["tb_rows"] = [
        _row("4", "מכירות", [-100000] * 6 + [0] * 6, income=True, kind="revenue", section="הכנסות"),
        _row("35", "שכר עבודה", [10000] * 6 + [0] * 6, category="שכר"),
        _row("31", "שכר דירה", [2000, 2000, 2000, 2000, 0, 2000] + [0] * 6, category="שכירות"),
        _row("30", "אגרות", [1200, 0, 0, 0, 0, 0] + [0] * 6),
    ]
    d["tb_rows_prev_year"] = []
    d["adjustments"] = []
    return d


def test_table_sums_replace_linear_factor():
    r = compute(ClientInput.from_dict(_base())).to_dict()
    t = r["months_table"]
    assert t["through_month"] == 6
    rev = next(x for x in t["rows"] if x["id"] == "4")
    assert [c["src"] for c in rev["cells"]] == ["file"] * 6 + ["estimate"] * 6
    assert rev["total"] == 1_200_000                      # 6 × 100 אלף + 6 × אומדן 100 אלף
    rent = next(x for x in t["rows"] if x["id"] == "31")
    assert rent["cells"][4]["src"] == "gap" and rent["cells"][4]["v"] == 2000     # מאי – חור, אומדן ממוצע
    fees = next(x for x in t["rows"] if x["id"] == "30")
    assert fees["cells"][1]["src"] == "file" and fees["cells"][1]["v"] == 0       # שורה לא סדירה – אין חור
    assert fees["cells"][6]["v"] == 200 and fees["method"] == "קצב"                # 1200 ÷ 6 – קצב
    assert t["annual"]["revenue"] == 1_200_000
    assert r["s62a"]["personal_effort_income"] == 1_200_000 or r["s62a"]["total_revenue"] == 1_200_000 if "total_revenue" in r["s62a"] else True
    assert any(i["key"] == "tb:31" and i["month"] == 5 and i["status"] == "pending" for i in r["estimate_items"])


def test_seasonality_from_prev_year():
    d = _base()
    # שנה קודמת: מכירות 50 אלף בחודשים 1–6 ו-150 אלף בחודשים 7–12 → השנה פי 2 → אומדן 300 אלף לחודש
    d["tb_rows_prev_year"] = [_row("4", "מכירות", [-50000] * 6 + [-150000] * 6, income=True, kind="revenue", section="הכנסות")]
    r = compute(ClientInput.from_dict(d)).to_dict()
    rev = next(x for x in r["months_table"]["rows"] if x["id"] == "4")
    assert rev["method"] == "עונתיות" and rev["cells"][11]["v"] == 300000
    assert rev["total"] == 600000 + 1_800_000


def test_manual_cell_overrides_and_recomputes():
    d = _base()
    r0 = compute(ClientInput.from_dict(d)).to_dict()
    d["adjustments"] = [{"key": "tb:35", "month": 9, "kind": "manual", "amount": 40000, "note": "בונוס", "by": "אברהם", "at": "2026-10-15T10:00:00"}]
    r1 = compute(ClientInput.from_dict(d)).to_dict()
    sal = next(x for x in r1["months_table"]["rows"] if x["id"] == "35")
    assert sal["cells"][8]["src"] == "manual" and sal["cells"][8]["v"] == 40000 and sal["cells"][8]["base"] == 10000
    assert r1["months_table"]["annual"]["expenses"] - r0["months_table"]["annual"]["expenses"] == 30000
    assert r1["data_breakdown"]["corrections_monthly"] == 30000
    assert r0["s62a"]["taxable_income_personal_effort"] - r1["s62a"]["taxable_income_personal_effort"] == 30000


def test_store_adjust_cell_and_supersede_on_reupload(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(S, "data_root", lambda: root)
    st = S.ClientStore()
    rec = st.save(_base(), None)
    cid = rec["id"]
    st.adjust(cid, "tb:35", 9, "manual", 40000, "בונוס")          # חודש שהיה אומדן
    st.adjust(cid, "tb:35", 3, "manual", 12000, "תיקון")           # חודש שהיה בקובץ
    rec = st.get(cid)
    assert any("שכר עבודה (מאזן בוחן) · חודש 9" in h["text"] for h in rec["history"] if h["kind"] == "תיקון")
    # קובץ חדש עד חודש 10 – התיקון על חודש 9 (היה אומדן) מוחלף; על חודש 3 (היה בקובץ) נשאר
    rows = _base()["tb_rows"]
    rows[0]["months"] = [-100000] * 10 + [0] * 2
    rows[1]["months"] = [10000] * 10 + [0] * 2
    new = st.apply_import(cid, {"data_through_month": 10, "tb_rows": rows}, {}, "מאזן בוחן 2026")
    keys = {(a["key"], a["month"]) for a in new["input"]["adjustments"]}
    assert ("tb:35", 3) in keys and ("tb:35", 9) not in keys
    assert any("הוחלפו על ידי הקובץ 1" in h["text"] for h in new["history"])
    sal = next(x for x in new["result"]["months_table"]["rows"] if x["id"] == "35")
    assert sal["cells"][8]["src"] == "file" and sal["cells"][2]["src"] == "manual"


def test_rollover_moves_rows_to_prev_year(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(S, "data_root", lambda: root)
    st = S.ClientStore()
    rec = st.save(_base(), None)
    st.adjust(rec["id"], "tb:35", 9, "manual", 40000, "")
    new = st.rollover_year(rec["id"])
    inp = new["input"]
    assert inp["tb_rows"] == [] and len(inp["tb_rows_prev_year"]) == 4
    assert not any(a.get("month") for a in inp["adjustments"])
    assert new["result"]["months_table"] is None


def test_cycle_detection_semi_annual_and_quarterly():
    from trapped_profits.engine import _cycle_of
    assert _cycle_of([0, 6], [0, 6]) == 6                    # שניים השנה + אישור מהשנה הקודמת
    assert _cycle_of([0, 6], []) == 6                        # חצי-שנתי – שניים מספיקים
    assert _cycle_of([2, 5], [], 8) == 3                     # מרץ+יוני, הבא ספטמבר – עוד לא הגיע → מחזורי
    assert _cycle_of([0, 3], [], 8) is None                  # ינו+אפר, יולי היה אמור להגיע ולא → לא מחזורי
    assert _cycle_of([2, 5], [2, 5, 8, 11]) == 3
    assert _cycle_of([0, 3, 6], []) == 3                     # שלושה במרווח זהה
    assert _cycle_of([0, 2, 5], []) is None                  # מרווחים שונים
    assert _cycle_of([6], [0, 6]) == 6                       # אחד השנה, שלב תואם לשנה קודמת
    assert _cycle_of([5], [0, 6]) is None                    # שלב לא תואם
    d = _base()
    d["data_through_month"] = 8
    d["tb_rows"].append(_row("50", "חשמל", [3000, 0, 0, 3000, 0, 0, 3000, 0, 0, 0, 0, 0]))   # ינו/אפר/יול → אוק
    r = compute(ClientInput.from_dict(d)).to_dict()
    row = next(x for x in r["months_table"]["rows"] if x["id"] == "50")
    assert row["method"] == "מחזורי · כל 3 חודשים"
    assert [c["v"] for c in row["cells"][8:]] == [0, 3000, 0, 0]
    assert row["total"] == 12000


def test_run_rate_for_non_key_rows_and_average_for_key_rows():
    d = _base()
    d["data_through_month"] = 8
    d["tb_rows"].append(_row("60", "הוצאות רכב", [8400] * 5 + [0, 0, 16800] + [0] * 4))     # דילוג ותשלום כפול
    d["tb_rows"][1]["months"] = [10000] * 4 + [0] + [10000] * 3 + [0] * 4                       # שכר עם חור במאי
    r = compute(ClientInput.from_dict(d)).to_dict()
    car = next(x for x in r["months_table"]["rows"] if x["id"] == "60")
    assert car["method"] == "קצב" and car["cells"][8]["v"] == 7350                            # 58,800 ÷ 8, לא 9,800
    sal = next(x for x in r["months_table"]["rows"] if x["id"] == "35")
    assert sal["method"] == "ממוצע" and sal["cells"][4]["src"] == "gap" and sal["cells"][8]["v"] == 10000


def test_past_correction_moves_future_estimates():
    d = _base()
    d["data_through_month"] = 8
    d["tb_rows"].append(_row("16", "קניות סחורה", [100000] * 8 + [0] * 4, category="קניות", section="עלויות ייצור"))
    r0 = compute(ClientInput.from_dict(d)).to_dict()
    row0 = next(x for x in r0["months_table"]["rows"] if x["id"] == "16")
    assert row0["method"] == "קצב" and row0["cells"][8]["v"] == 100000
    d["adjustments"] = [{"key": "tb:16", "month": 3, "kind": "manual", "amount": 1_100_000, "note": "", "by": "א", "at": "x"}]   # +מיליון במרץ
    r1 = compute(ClientInput.from_dict(d)).to_dict()
    row1 = next(x for x in r1["months_table"]["rows"] if x["id"] == "16")
    assert row1["cells"][2]["src"] == "manual" and row1["cells"][8]["v"] == 225000            # (800K + 1M) ÷ 8
    assert row1["total"] == 1_800_000 + 4 * 225000
    assert r0["months_table"]["annual"]["profit"] - r1["months_table"]["annual"]["profit"] == 1_500_000   # 1M + 4 × 125K


def test_approve_all_and_gross_profit(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(S, "data_root", lambda: root)
    st = S.ClientStore()
    d = _base()
    d["tb_rows"].append(_row("16", "קניות סחורה", [40000] * 6 + [0] * 6, category="קניות", section="עלויות ייצור"))
    d["s62a"]["gross_profit_history"] = [{"year": 2025, "revenue": 1_000_000, "gross_profit": 550_000, "rate": 0.55}]
    rec = st.save(d, None)
    cid = rec["id"]
    t = rec["result"]["months_table"]
    assert any(i["status"] == "pending" for i in rec["result"]["estimate_items"])          # חור בשכירות במאי
    pur = next(x for x in t["rows"] if x["id"] == "16")
    assert pur["cogs"] is True and next(x for x in t["rows"] if x["id"] == "35")["cogs"] is False
    assert t["annual"]["cogs"] == 480000 and t["annual"]["gross"] == 1_200_000 - 480000
    assert t["gross_history"][0]["rate"] == 0.55
    st.adjust(cid, "tb:35", 2, "manual", 15000, "")
    new = st.approve_tb(cid)
    t2 = new["result"]["months_table"]
    assert t2["approved"] and not any(i["status"] == "pending" for i in new["result"]["estimate_items"])
    sal = next(x for x in t2["rows"] if x["id"] == "35")
    assert sal["cells"][1]["src"] == "manual" and sal["cells"][8]["src"] == "accepted"
    assert any("מאזן בוחן אושר" in h["text"] for h in new["history"])
    new = st.set_tb_cogs(cid, "35", True)
    assert new["result"]["months_table"]["annual"]["cogs"] > 480000
    # קובץ חדש עם חודש אחר – האישור פג
    rows = new["input"]["tb_rows"]
    new = st.apply_import(cid, {"data_through_month": 7, "tb_rows": rows}, {}, "מאזן בוחן")
    assert new["result"]["months_table"]["approved"] is None and new["result"]["months_table"]["approved_stale"]
    new = st.approve_tb(cid, undo=True)
    assert new["input"]["tb_approved"] == {}


def test_grants_refunds_and_cogs_default():
    d = _base()
    d["data_through_month"] = 9
    d["tb_rows"] = [
        _row("4", "הכנסות/מכירות", [-100000] * 9 + [0] * 3, income=True, kind="revenue", section="הכנסות ממכירות ומתן שירותים", group="מכירות - 70"),
        _row("5", "הכנסות ממענקים", [0] * 5 + [-55355, -25169, 0, 0, 0, 0, 0], income=True, kind="revenue", section="הכנסות ממכירות ומתן שירותים", group="הכנסות אחרות - 1090"),
        _row("35", "שכר עבודה", [50000] * 9 + [0] * 3, category="שכר", section="עלויות ייצור"),
        _row("99", "החזר מילואים ביטוח לאומי", [-3554, -2367, -1113, -28306, -10748, -7782, -7782, -601, 0, 0, 0, 0], category="עלויות מעסיק", section="עלויות ייצור"),
        _row("71", "הקמת פרויקטים", [1000] * 9 + [0] * 3, section="עלויות ייצור"),
    ]
    r = compute(ClientInput.from_dict(d)).to_dict()
    rows = {x["id"]: x for x in r["months_table"]["rows"]}
    g = rows["5"]
    assert g["kind"] == "other_income" and g["method"] == "ללא אומדן" and all(c["v"] == 0 for c in g["cells"][9:])
    d2 = dict(d); d2["tb_rows"] = [x for x in d["tb_rows"] if x["id"] != "5"]
    r2 = compute(ClientInput.from_dict(d2)).to_dict()
    assert round(r["s62a"]["personal_effort_income"]) == round(r2["s62a"]["personal_effort_income"])   # המענק לא בהכנסה מעתירת יגיעה
    assert round(r["s62a"]["taxable_income_personal_effort"]) == round(r2["s62a"]["taxable_income_personal_effort"])
    ref = rows["99"]
    # 22.10: החזר (שורת הוצאה שלילית) – בלי חורים ובלי אומדן קדימה (בדיקה לאחור: הקצב היה הופך סימן)
    assert not any(c["src"] == "gap" for c in ref["cells"]) and ref["method"] == "ללא אומדן"
    assert rows["71"]["cogs"] and not rows["35"]["cogs"]                         # שכר לא בעלות המכר כברירת מחדל



def test_backtest_rules_22_10():
    """22.10 (בדיקה לאחור על שנים שלמות): עונתיות מוגבלת, חורים רק בסעיפים חודשיים, שכר לפי מגמה, חודש חריג לא בבסיס."""
    from trapped_profits.engine import _tb_table
    m = lambda *v: list(v) + [0] * (12 - len(v))
    rows = [
        {"id": "r", "name": "הכנסות", "income": True, "kind": "revenue", "months": m(-100, -100, 0, -100, -100, -100, -100, -100)},
        {"id": "s", "name": "שכר עבודה", "income": False, "kind": "expense", "category": "שכר", "months": m(10, 10, 10, 10, 10, 0, 16, 16)},
        {"id": "k", "name": "עבודות חוץ-קבלני משנה", "income": False, "kind": "expense", "category": "קבלני משנה", "months": m(5, 0, 5, 5, 0, 5, 5, 5)},
        {"id": "o", "name": "אחזקה", "income": False, "kind": "expense", "category": None, "months": m(2, 2, 2, 30, 2, 2, 2, 2)},
        {"id": "p", "name": "קניות", "income": False, "kind": "expense", "category": "קניות", "months": m(1, 0, 0, 0, 0, 0, 0, 1)},
    ]
    prev = [{"id": "p", "name": "קניות", "income": False, "months": [0, 0, 0, 0, 0, 0, 0, 1, 50, 50, 50, 50]}]
    ci = ClientInput.from_dict({"structure": {"name": "x", "tax_year": 2026}, "tb_rows": rows, "tb_rows_prev_year": prev, "data_through_month": 8})
    _, _, mt, _ = _tb_table(ci)
    R = {r["id"]: r for r in mt["rows"]}
    assert all(c["src"] != "gap" for c in R["r"]["cells"])                       # חודש בלי הכנסה – לא "חור"
    assert R["s"]["cells"][5]["src"] == "gap"                                    # שכר 0 ביוני – חור
    assert R["s"]["cells"][8]["v"] == 14                                         # מגמה: (10+16+16)/3
    assert all(c["src"] != "gap" for c in R["k"]["cells"])                       # קבלני משנה – לא חודשי
    assert R["o"]["cells"][8]["v"] == 2                                          # חודש חריג (30) לא בבסיס
    assert R["p"]["method"] != "עונתיות" and R["p"]["total"] < 10                 # היחס מתפוצץ – לא עונתיות
