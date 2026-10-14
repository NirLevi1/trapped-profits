"""החלטות 14–18: סטטוס טיפול, נתון מיושן, הגדרות ודגלים."""
import json, tempfile
from pathlib import Path
from trapped_profits.store import ClientStore, HANDLING_STATUSES

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"


def _store():
    return ClientStore(Path(tempfile.mkdtemp())), json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_handling_status_persists_and_survives_recompute():
    s, inp = _store()
    rec = s.save(inp)
    assert rec["handling"]["status"] == HANDLING_STATUSES[0]
    s.set_handling(rec["id"], "הוחלט: חלוקה", "סוכם 430 אלף")
    rec2 = s.save(inp, rec["id"])
    assert rec2["handling"]["status"] == "הוחלט: חלוקה" and rec2["handling"]["note"] == "סוכם 430 אלף"


def test_stale_flag_from_data_as_of():
    s, inp = _store()
    inp["data_as_of"] = "2025-01-01"
    rec = s.save(inp)
    assert s.list()[0]["stale"] is True
    s.settings.save({"stale_days": 100000})
    assert s.list()[0]["stale"] is False


def test_settings_flags_apply_to_clients():
    s, inp = _store()
    inp["distributions"].update({"dividend_in_determining_period": 5_760_000, "determining_period_paid_and_taxed": True})
    a = s.save(inp)["result"]["simulator"]["option_50pct"]
    s.settings.save({"flags": {"deduct_transition_from_50pct_base": True}})
    s.recompute_all()
    b = s.list()[0]["result"]["simulator"]["option_50pct"]
    assert a == 1_950_000 and b == 350_000


def test_new_client_with_existing_company_id_is_rejected():
    s, inp = _store()
    s.save(inp)
    import pytest
    with pytest.raises(ValueError):
        s.save(inp)                      # לקוח "חדש" עם אותו ח.פ.
    s.save(inp, s.list()[0]["id"])      # עריכה – מותר
    assert len(s.list()) == 1


def test_data_as_of_is_normalized_to_iso():
    s, inp = _store()
    inp["data_as_of"] = "30.9.2026"
    rec = s.save(inp)
    assert rec["input"]["data_as_of"] == "2026-09-30"
    inp["data_as_of"] = "מחצית השנה"
    rec = s.save(inp, rec["id"])
    assert rec["input"]["data_as_of"] == "מחצית השנה"


def test_export_when_file_locked_gives_hebrew_error(monkeypatch):
    s, inp = _store()
    rec = s.save(inp)
    import trapped_profits.documents as docs
    def boom(*a, **k): raise PermissionError("locked")
    monkeypatch.setattr(docs, "render_docx", boom)
    import pytest
    with pytest.raises(RuntimeError, match="פתוח"):
        s.export_document(rec["id"], "accountant", "docx")


def test_recompute_only_outdated_logic_version():
    s, inp = _store()
    rec = s.save(inp)
    p = s._path(rec["id"])
    old = json.loads(p.read_text(encoding="utf-8")); old["logic_version"] = "2000.01.01-a"
    p.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    inp2 = dict(inp); inp2["structure"] = {**inp["structure"], "company_id": "515000099"}
    s.save(inp2)
    assert s.recompute_all(only_outdated=True) == 1
    assert s.recompute_all(only_outdated=True) == 0


def test_delete_archives_everything():
    s = ClientStore(Path(tempfile.mkdtemp()) / "clients")
    inp = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    rec = s.save(inp)
    name = s.safe_name(inp["structure"]["name"])
    data = s.root.parent
    (data / "files" / name / "2026-Q4").mkdir(parents=True)
    (data / "files" / name / "2026-Q4" / "x.csv").write_text("a")
    (data / "reports").mkdir(exist_ok=True)
    (data / "reports" / f"{name} – דוח לרואה חשבון 2026.pdf").write_bytes(b"%PDF")
    assert s.delete(rec["id"]) is True
    assert s.get(rec["id"]) is None and not (data / "files" / name).exists()
    arch = list((data / "_deleted").glob(f"{name} – *"))
    assert len(arch) == 1
    assert (arch[0] / f"{rec['id']}.json").exists() and (arch[0] / "files" / "2026-Q4" / "x.csv").exists()
    assert any((arch[0] / "reports").glob("*.pdf"))
    assert s.delete(rec["id"]) is False


def test_field_records_and_revert():
    s = ClientStore(Path(tempfile.mkdtemp()) / "clients")
    inp = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    rec = s.save(inp)
    cid = rec["id"]
    orig = inp["retained"]["balance_sheet_retained_earnings"]
    # עריכה ידנית → רשומה עם ערך קודם, מי ומתי
    rec = s.update_field(cid, "retained.balance_sheet_retained_earnings", orig + 1000)
    m = rec["field_meta"]["retained.balance_sheet_retained_earnings"]
    assert m["state"] == "manual" and m["by"] == "המשרד" and m["prev"][-1]["value"] == orig
    # שמירה חוזרת של הטופס עם אותו מצב – לא רשומה חדשה
    rec2 = s.save(rec["input"], cid, field_meta=rec["field_meta"])
    assert rec2["field_meta"]["retained.balance_sheet_retained_earnings"]["at"] == m["at"]
    assert len(rec2["field_meta"]["retained.balance_sheet_retained_earnings"]["prev"]) == 1
    # שינוי בטופס בלי מצב מפורש = ידני, והקודם נשמר
    inp2 = json.loads(json.dumps(rec2["input"]))
    inp2["retained"]["balance_sheet_retained_earnings"] = orig + 2000
    rec3 = s.save(inp2, cid, field_meta=rec2["field_meta"])
    assert len(rec3["field_meta"]["retained.balance_sheet_retained_earnings"]["prev"]) == 2
    # ביטול שדה → חזרה ל-orig+1000, ואז ביטול היום → חזרה ל-orig
    rec4 = s.revert_field(cid, "retained.balance_sheet_retained_earnings")
    assert rec4["input"]["retained"]["balance_sheet_retained_earnings"] == orig + 1000
    assert rec4["history"][-1]["kind"] == "ביטול"
    rec5 = s.revert_today(cid)
    assert rec5["input"]["retained"]["balance_sheet_retained_earnings"] == orig
    import pytest
    with pytest.raises(ValueError):
        s.revert_field(cid, "retained.balance_sheet_retained_earnings")


def test_rollover_year_carries_values():
    s = ClientStore(Path(tempfile.mkdtemp()) / "clients")
    inp = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    inp["structure"]["last_closed_report_year"] = 2025
    inp["distributions"]["dividends_taxed_current_year"] = 150000
    inp["data_through_month"] = 6
    rec = s.save(inp)
    cid, ty = rec["id"], inp["structure"]["tax_year"]
    exp_cur = inp["shields"]["expenses_current_year"]
    new = s.rollover_year(cid)
    i = new["input"]
    assert i["structure"]["tax_year"] == ty + 1
    assert i["distributions"]["dividends_prev_year"] == 150000 and i["distributions"]["dividends_taxed_current_year"] == 0
    assert i["shields"]["expenses_prev_year"] == round(exp_cur * 2) and i["shields"]["expenses_current_year"] == 0
    assert i["data_through_month"] is None
    assert new["field_meta"]["distributions.dividends_prev_year"]["state"] == "carried"
    assert "מעבר שנה" in new["field_meta"]["distributions.dividends_prev_year"]["source"]
    assert str(ty) in new["years"] and new["years"][str(ty)]["input"]["distributions"]["dividends_taxed_current_year"] == 150000
    assert new["history"][-1]["kind"] == "מעבר שנה" and new["rollover_checklist"]
    assert "דיבידנד ששולם עליו מס השנה" in new["missing_human"]
    # השנה החדשה היא תרחיש ב׳ (הדוח הסגור ישן בשנה) והעודפים מגולגלים
    assert new["result"]["retained"]["is_estimate"] if "is_estimate" in new["result"]["retained"] else True
    assert new["result"] is not None


def test_revert_field_without_prior_state_returns_to_missing():
    s = ClientStore(Path(tempfile.mkdtemp()) / "clients")
    inp = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    inp["s62a"]["owner_salary_current_year"] = None
    rec = s.save(inp)
    rec = s.update_field(rec["id"], "s62a.owner_salary_current_year", 200000)
    assert "שכר בעלים ששולם השנה" not in rec["missing_human"]
    rec = s.revert_field(rec["id"], "s62a.owner_salary_current_year")
    assert rec["input"]["s62a"]["owner_salary_current_year"] is None
    assert "s62a.owner_salary_current_year" not in rec["field_meta"]
    assert "שכר בעלים ששולם השנה" in rec["missing_human"]


def test_data_root_pointer(monkeypatch, tmp_path):
    from trapped_profits import store as st
    monkeypatch.setattr(st, "app_dir", lambda: tmp_path)
    assert st.data_root() == tmp_path / "data"
    other = tmp_path / "shared"
    st.set_data_root(other)
    assert st.data_root() == other
    assert ClientStore().root == other / "clients"
