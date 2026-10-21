"""21.10: בודק שני – השוואה, סתירות, בחירה, עבודה בלי מפתח (בלי רשת: המודל מוחלף בפונקציה)."""
import json

import pytest

from trapped_profits import ai_check
from trapped_profits.ai_check import AIError, compare_annual, model_annual_fields, verify_annual, verify_tb
from trapped_profits.store import ClientStore


def _model(retained=500000, dep=12000, name='חברה לדוגמה בע"מ'):
    return {"company_name": name, "report_year": 2025, "fixed_assets": {"cost_closing": 200000, "depreciation_for_year": dep, "page": 5},
            "years": [{"year": 2025, "retained_earnings": retained, "general_admin_expenses": 300000, "finance_expenses": 1000,
                       "cash_and_equivalents": 50000, "share_capital": 100, "pages": {"retained_earnings": 3}},
                      {"year": 2024, "retained_earnings": 400000, "general_admin_expenses": 250000}]}


def _ours():
    f = {"structure.name": 'חברה לדוגמה בע"מ', "structure.last_closed_report_year": 2025,
         "retained.balance_sheet_retained_earnings": 500000.0, "shields.expenses_prev_year": 301000.0,
         "shields.expenses_prev2_year": 250000.0, "shields.special_loans_deposits_cash": 50000.0,
         "shields.total_assets_cost": 200000.0, "shields.total_assets_cost_is_net": False,
         "shields.depreciation_annual_estimate": 12000.0, "distributions.retained_at_start_day": 400000.0}
    return f, {k: "קורא" for k in f}


def test_mapping_same_as_ours():
    mf, src, y = model_annual_fields(_model(), 2026)
    assert y == 2025
    assert mf["retained.balance_sheet_retained_earnings"] == 500000
    assert mf["shields.expenses_prev_year"] == 301000            # הנהלה + מימון
    assert mf["distributions.retained_at_start_day"] == 400000   # עודפים לתום 2024
    assert mf["shields.total_assets_cost"] == 200000 and mf["shields.total_assets_cost_is_net"] is False


def test_agree_conflict_and_one_sided():
    ours, src = _ours()
    mf, msrc, _ = model_annual_fields(_model(dep=30000, name='חברה לדוגמה, בע"מ'), 2026)
    c = compare_annual(ours, src, mf, msrc)
    assert list(c["conflicts"]) == ["shields.depreciation_annual_estimate"]
    assert "shields.depreciation_annual_estimate" not in c["fields"]           # סתירה – לא נכנס עד שבוחרים
    assert "✓ אומת" in c["sources"]["retained.balance_sheet_retained_earnings"]
    assert "structure.name" not in c["conflicts"]                              # פסיק – לא סתירה
    assert c["fields"]["shields.share_capital_and_premium"] == 100              # רק המודל מצא – נלקח


def test_no_key_or_failure_keeps_ours():
    ours, src = _ours()
    r = {"fields": dict(ours), "sources": dict(src), "notes": []}
    def boom(*a, **k):
        raise AIError("נגמר הקרדיט בחשבון – צריך להטעין")
    verify_annual(r, __file__, 2026, "k", caller=lambda *a, **k: boom())
    assert r["fields"]["retained.balance_sheet_retained_earnings"] == 500000
    assert r["fields"]["ai_annual"]["ok"] is False
    assert any("נגמר הקרדיט" in n for n in r["notes"])


def test_tb_classification_conflicts():
    rows = [{"id": "1", "name": "הכנסות ממכירות", "income": True, "kind": "revenue", "months": [-100] * 12},
            {"id": "2", "name": "הכנסות שונות", "income": True, "kind": "revenue", "months": [-10] * 12},
            {"id": "3", "name": "קבלני משנה", "income": False, "kind": "expense", "category": "קבלני משנה", "months": [50] * 12},
            {"id": "4", "name": "שכירות", "income": False, "kind": "expense", "months": [5] * 12}]
    ans = {"rows": [{"id": "1", "kind": "revenue"}, {"id": "2", "kind": "other_income", "reason": "לא מהפעילות"},
                    {"id": "3", "cogs": True}, {"id": "4", "cogs": True}]}
    r = verify_tb({"fields": {"tb_rows": rows}, "notes": []}, "k", caller=lambda *a, **k: ans)
    conf = r["fields"]["ai_tb"]["conflicts"]
    assert set(conf) == {"2", "4"}
    assert conf["2"] == {"type": "kind", "name": "הכנסות שונות", "ours": "revenue", "model": "other_income", "reason": "לא מהפעילות"}


def _store(tmp_path):
    st = ClientStore(tmp_path / "clients")
    rec = st.save({"structure": {"name": "בדיקה", "tax_year": 2026}})
    return st, rec


def test_conflict_blocks_until_chosen(tmp_path):
    st, rec = _store(tmp_path)
    ours, src = _ours()
    mf, msrc, _ = model_annual_fields(_model(dep=30000), 2026)
    c = compare_annual(ours, src, mf, msrc)
    fields = {**c["fields"], "ai_annual": {"at": "2000-01-01T00:00:00", "ok": True, "msg": "", "conflicts": c["conflicts"]}}
    rec = st.apply_import(rec["id"], fields, c["sources"], "דוח")
    assert any("סתירה בין הקוראים: פחת שנתי" in x for x in rec["missing_human"])
    assert "ai_annual" not in rec["pending_file_fields"]
    rec = st.resolve_ai(rec["id"], "shields.depreciation_annual_estimate", "model")
    assert rec["input"]["shields"]["depreciation_annual_estimate"] == 30000
    assert not rec["input"]["ai_annual"]["conflicts"]
    assert not any("סתירה" in x for x in rec["missing_human"])
    assert rec["field_meta"]["shields.depreciation_annual_estimate"]["state"] == "approved"


def test_manual_edit_closes_conflict(tmp_path):
    st, rec = _store(tmp_path)
    conf = {"shields.total_assets_cost": {"label": "עלות הנכסים", "ours": 1, "model": 2, "ours_also": {}, "model_also": {}}}
    rec = st.apply_import(rec["id"], {"ai_annual": {"at": "2000-01-01T00:00:00", "conflicts": conf}}, {}, "דוח")
    rec = st.update_field(rec["id"], "shields.total_assets_cost", 5)
    assert not rec["input"]["ai_annual"]["conflicts"]


def test_tb_kind_choice_changes_revenue(tmp_path):
    st, rec = _store(tmp_path)
    rows = [{"id": "1", "name": "הכנסות", "section": "הכנסות", "group": "", "income": True, "kind": "revenue", "months": [-100000] * 12},
            {"id": "2", "name": "הכנסות שונות", "section": "הכנסות", "group": "", "income": True, "kind": "revenue", "months": [-50000] * 12},
            {"id": "3", "name": "שכר", "section": "הוצאות", "group": "", "income": False, "kind": "expense", "category": "שכר", "months": [60000] * 12}]
    ai = {"at": "2000-01-01T00:00:00", "ok": True, "conflicts": {"2": {"type": "kind", "name": "הכנסות שונות", "ours": "revenue", "model": "other_income"}}}
    rec = st.apply_import(rec["id"], {"tb_rows": rows, "data_through_month": 12, "ai_tb": ai}, {}, "מאזן בוחן")
    before = rec["result"]["months_table"]["annual"]["revenue"]
    rec = st.resolve_tb_ai(rec["id"], "2", "model")
    after = rec["result"]["months_table"]["annual"]
    assert before == 1800000 and after["revenue"] == 1200000 and after["other_income"] == 600000
    assert not rec["input"]["ai_tb"]["conflicts"] and rec["input"]["tb_kind"] == {"2": "other_income"}


def test_settings_hide_key(tmp_path, monkeypatch):
    import sys, types
    monkeypatch.setitem(sys.modules, "webview", sys.modules.get("webview") or types.ModuleType("webview"))
    import app
    api = app.Api.__new__(app.Api)
    api.store = ClientStore(tmp_path / "clients")
    api.store.settings.save({"ai_key": "sk-secret-1234"})
    st = api.get_settings()
    assert "ai_key" not in st and st["ai_key_tail"] == "1234"
    api.save_settings({"stale_days": 30})
    assert api._ai_key()[0] == "sk-secret-1234"                     # שמירת הגדרות אחרות לא מוחקת את המפתח
    monkeypatch.setattr(ai_check, "test_key", lambda k, m=None: {"ok": False, "msg": "המפתח לא תקין – לבדוק בהגדרות"})
    r = api.set_ai_key("bad")
    assert r["ok"] is False and api._ai_key()[0] == "sk-secret-1234"  # מפתח שנכשל לא נשמר


def test_reread_old_reports_opens_choices(tmp_path, monkeypatch):
    """21.10: עדכון של הקורא – הדוח השמור נקרא שוב; ערך שונה לא נדרס אלא נפתח לבחירה; שדה שהוקלד – לא נוגעים."""
    from trapped_profits import importers
    st = ClientStore(tmp_path / "clients")
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF")
    rec = st.save({"structure": {"name": "מיכל", "tax_year": 2026}})
    rec = st.apply_import(rec["id"], {"retained.balance_sheet_retained_earnings": 0.0, "shields.total_assets_cost": 100.0,
                                      "shields.depreciation_annual_estimate": 50.0}, {}, "דוח",
                          source={"slot": "annual_report", "title": "דוח", "file": "report.pdf", "path": str(pdf)})
    st.update_field(rec["id"], "shields.total_assets_cost", 999.0)          # אברהם הקליד
    full = st.get(rec["id"]); full["report_parser_version"] = "old"; st._write(rec["id"], full)
    monkeypatch.setattr(importers, "import_slot", lambda *a, **k: {"fields": {
        "retained.balance_sheet_retained_earnings": 691283.0, "shields.total_assets_cost": 21035.0,
        "shields.depreciation_annual_estimate": 50.0}, "sources": {"retained.balance_sheet_retained_earnings": "מאזן"}})
    out = st.reread_reports()
    assert out["changed"] == 1 and out["fields"] == 1
    rec = st.get(rec["id"])
    conf = rec["input"]["ai_annual"]["conflicts"]
    assert list(conf) == ["retained.balance_sheet_retained_earnings"]
    assert rec["input"]["retained"]["balance_sheet_retained_earnings"] == 0          # לא נדרס
    assert any("הקורא החדש מצא ערך אחר" in x for x in rec["missing_human"])
    assert st.reread_reports()["clients"] == 0                                        # פעם אחת לכל גרסה
    rec = st.resolve_ai(rec["id"], "retained.balance_sheet_retained_earnings", "model")
    assert rec["input"]["retained"]["balance_sheet_retained_earnings"] == 691283
    assert "הקורא החדש" in rec["history"][-1]["text"]
