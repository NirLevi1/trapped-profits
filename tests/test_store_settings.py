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
