"""22.10: ייבוא מתיקיית איסוף – בלי לקרוא קבצים אמיתיים (import_slot מוחלף)."""
from pathlib import Path

from trapped_profits import folder_import as fi, importers
from trapped_profits.store import ClientStore


def _tree(root: Path):
    files = {
        "גלגש הנדסה בעמ/2025/דוחות כספיים.pdf": b"%PDF-a",
        "גלגש הנדסה בעמ/2025/דוחות כספיים - חבילת דוחות מלאה אחרת.pdf": b"%PDF-other",
        "גלגש הנדסה בעמ/2025/דוחות כספיים - נייר עבודה.pdf": b"%PDF-draft",
        "גלגש הנדסה בעמ/2026/רווח והפסד 2026.csv": b"tb26",
        "גלגש הנדסה בעמ/2026/כרטסת 2026.xls": b"l26",
        "גלגש הנדסה בעמ/2025/רווח והפסד 2025.csv": b"tb25",
        "גלגש הנדסה בעמ/2027/רווח והפסד 2027.csv": b"tb27",
        "גלגש הנדסה בעמ/מאזן לא מבוקר 2016.pdf": b"%PDF-old",
        "_יומן ריווחית/1.csv": b"x",
    }
    for k, v in files.items():
        p = root / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(v)


def _fake(calls):
    def imp(slot, path, ty=None):
        calls.append((slot, Path(path).name))
        if slot == "annual_report":
            other = "אחרת" in Path(path).name
            return {"year": 2025, "fields": {"structure.name": "מיכל ורז נדלן בע\"מ" if other else "גלגש הנדסה בע\"מ",
                                              "structure.last_closed_report_year": 2025,
                                              "retained.balance_sheet_retained_earnings": 985490.0, "shields.expenses_prev_year": 3000000.0},
                    "sources": {}, "notes": []}
        if slot == "trial_balance":
            return {"year": 2026, "fields": {"data_through_month": 9, "shields.expenses_current_year": 2000000.0 if b"tb26" else 0}, "sources": {}}
        if slot == "trial_balance_prev":
            return {"year": 2025, "fields": {"shields.expenses_prev_year": 1.0, "tb_rows_prev_year": [{"id": "1"}]}, "sources": {}}
        return {"year": 2026, "fields": {"s62a.top_customers": [{"name": "אלביט", "amount": 100}]}, "sources": {}}
    return imp


def test_new_client_update_and_manual_kept(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _tree(root)
    calls = []
    monkeypatch.setattr(importers, "import_slot", _fake(calls))
    st = ClientStore(tmp_path / "data" / "clients")
    pl = fi.plan(root, st, 2026)
    assert [it["status"] for it in pl["items"]] == ["חדש"]
    notes = " ".join(pl["items"][0]["notes"])
    assert "נייר עבודה" in notes and "לא בתוך תיקיית שנה" in notes and "2027" in notes
    s = fi.run(root, st, 2026)
    r = s["results"][0]
    assert r["status"] == "נוסף"
    rec = st.get(r["client_id"])
    assert rec["input"]["structure"]["name"] == 'גלגש הנדסה בע"מ'
    assert rec["input"]["shields"]["expenses_prev_year"] == 3000000.0           # רווח והפסד 2025 לא דורס את הדוח
    assert rec["input"]["tb_rows_prev_year"] == [{"id": "1"}]                   # אבל השורות נכנסות (עונתיות)
    assert ("annual_report", "דוחות כספיים - חבילת דוחות מלאה אחרת.pdf") not in calls or "דוחות כספיים.pdf" in [c[1] for c in calls]
    # ריצה שנייה – בלי שינוי
    assert fi.run(root, st, 2026)["plan"] == {"ללא שינוי": 1}
    # אברהם הקליד עודפים; הקובץ מתעדכן – לא נדרס, נפתחת סתירה
    st.update_field(rec["id"], "retained.balance_sheet_retained_earnings", 900000.0)
    (root / "גלגש הנדסה בעמ/2025/דוחות כספיים.pdf").write_bytes(b"%PDF-b")
    s = fi.run(root, st, 2026)
    assert s["results"][0]["status"] == "עודכן"
    rec = st.get(rec["id"])
    assert rec["input"]["retained"]["balance_sheet_retained_earnings"] == 900000.0
    c = rec["input"]["ai_annual"]["conflicts"]["retained.balance_sheet_retained_earnings"]
    assert c["ours_name"] == "הוזן ידנית" and c["model"] == 985490.0


def test_other_company_report_rejected(tmp_path):
    files = {"pdf": {2025: [tmp_path / "a.pdf"]}}
    (tmp_path / "a.pdf").write_bytes(b"x")
    log = []
    p, r = fi.pick_annual_report(files, 2026, "גלגש הנדסה בעמ", log, parse=lambda p: {"year": 2025, "fields": {"structure.name": "קובילינסקי קופרשטיין"}})
    assert p is None and "לא תואם" in log[0]


def test_existing_client_matched_by_name(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _tree(root)
    monkeypatch.setattr(importers, "import_slot", _fake([]))
    st = ClientStore(tmp_path / "data" / "clients")
    rec = st.save({"structure": {"name": 'גלגש הנדסה בע"מ', "tax_year": 2026}})
    pl = fi.plan(root, st, 2026)
    assert pl["items"][0]["client_id"] == rec["id"] and pl["items"][0]["status"] == "לעדכון"


def test_lock(tmp_path):
    st = ClientStore(tmp_path / "clients")
    with fi.SyncLock(st):
        try:
            with fi.SyncLock(st):
                assert False
        except RuntimeError as e:
            assert "כבר רץ" in str(e)


def test_routes_minimum():
    """22.10 (אברהם): מינימום – דוח סגור + רווח והפסד מהשנה שאחריו ועד שנת המס; כרטסת לא חובה."""
    f = lambda pdf, tb: {"pdf": {y: ["x"] for y in pdf}, "tb": {y: "x" for y in tb}}
    assert fi.routes(f([2025], [2026]), 2026) == ([2025], "")
    assert fi.routes(f([2024, 2025], [2025, 2026]), 2026)[0] == [2025, 2024]
    assert fi.routes(f([2024], [2025, 2026]), 2026)[0] == [2024]
    assert fi.routes(f([2023], [2024, 2025, 2026]), 2026)[0] == [2023]
    ok, why = fi.routes(f([2024], [2026]), 2026)
    assert ok == [] and "רווח והפסד 2025" in why
    ok, why = fi.routes(f([2025], []), 2026)
    assert ok == [] and "רווח והפסד 2026" in why
    ok, why = fi.routes(f([], [2026]), 2026)
    assert ok == [] and "אין דוח סגור" in why


def test_not_ready_not_imported(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "רק דוח בעמ" / "2025").mkdir(parents=True)
    (root / "רק דוח בעמ" / "2025" / "דוחות כספיים.pdf").write_bytes(b"%PDF")
    (root / "רק דוח בעמ" / "2026").mkdir()
    (root / "רק דוח בעמ" / "2026" / "כרטסת 2026.xls").write_bytes(b"l")
    calls = []
    monkeypatch.setattr(importers, "import_slot", _fake(calls))
    st = ClientStore(tmp_path / "data" / "clients")
    s = fi.run(root, st, 2026)
    assert s["results"] == [] and calls == []
    assert s["other"][0]["status"] == "לא מוכן" and "רווח והפסד 2026" in s["other"][0]["notes"][0]


def test_backfill_ledger_months(tmp_path, monkeypatch):
    """22.10: כרטסת שנקלטה בלי חודשים – נקראת שוב מהעותק השמור ומקבלת חודשי שירות."""
    st = ClientStore(tmp_path / "clients")
    f = tmp_path / "l.xls"
    f.write_bytes(b"x")
    rec = st.save({"structure": {"name": "x", "tax_year": 2026}, "s62a": {"top_customers": [{"name": "מקאן", "amount": 10}]}})
    rec = st.apply_import(rec["id"], {}, {}, "כרטסת", source={"slot": "ledger", "title": "כרטסת", "file": "l.xls", "path": str(f)})
    monkeypatch.setattr(importers, "parse_ledger", lambda p: {"fields": {"s62a.top_customers": [{"name": "מקאן", "amount": 10, "months": ["2026-01", "2026-02"]}]}})
    assert st.backfill_ledger_months() == 1
    assert st.get(rec["id"])["input"]["s62a"]["top_customers"][0]["months"] == ["2026-01", "2026-02"]
    assert st.backfill_ledger_months() == 0
