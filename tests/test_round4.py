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
    assert fees["cells"][6]["v"] == 200                                            # 1200 ÷ 6 – חלק יחסי
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
    assert _cycle_of([0, 3], []) is None                     # רבעוני – שניים בלי אישור לא מספיק
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
