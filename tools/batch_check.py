"""בדיקה על תיקים אמיתיים: תיקייה לכל לקוח (דוח שנתי, מאזני בוחן, כרטסות) → JSON עם מה שנקרא וחושב.
הרצה: python tools/batch_check.py <תיקיית-לקוחות> <פלט.json>. הנתונים עצמם לא נשמרים במאגר."""
import sys, json, re, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trapped_profits.importers import import_slot, detect, _read
from trapped_profits.models import ClientInput
from trapped_profits.engine import compute

B = Path(sys.argv[1]); TY = 2026
def setp(d, k, v):
    p = k.split("."); t = d
    for x in p[:-1]: t = t.setdefault(x, {})
    t[p[-1]] = v

def file_year(f):
    m = re.search(r"(20\d\d)", f.name)
    if m: return int(m.group(1))
    try:
        txt = " ".join(" ".join(r) for r in _read(f)[:10])
        m = re.search(r"/(20\d\d)", txt); return int(m.group(1)) if m else None
    except Exception: return None

out = {}
for d in sorted(B.iterdir()):
    rep = {"files": {}, "notes": [], "errors": []}
    inp = {"structure": {"tax_year": TY}}
    pdfs = [f for f in d.iterdir() if f.suffix.lower() == ".pdf"]
    lag = 1
    for f in pdfs:
        try:
            r = import_slot("annual_report", f, TY)
            rep["files"][f.name] = {"slot": "annual_report", "year": r.get("year"), "n": len(r["fields"])}
            rep["notes"] += [f"PDF: {n}" for n in r.get("notes", [])]
            for k, v in r["fields"].items(): setp(inp, k, v)
            if r.get("year"): lag = max(1, min(3, TY - r["year"]))
        except Exception as e:
            rep["errors"].append(f"{f.name}: {e}")
    for f in sorted(d.iterdir()):
        if f.suffix.lower() == ".pdf": continue
        try:
            kind = detect(f); y = file_year(f)
            if kind not in ("trial_balance", "ledger"): rep["errors"].append(f"{f.name}: לא מזוהה ({kind})"); continue
            off = TY - (y or TY)
            if kind == "trial_balance":
                slot = {0: "trial_balance", 1: "trial_balance_prev", 2: "trial_balance_prev2"}.get(off)
                if slot == "trial_balance_prev" and lag < 2: slot = None
                if slot == "trial_balance_prev2" and lag < 3: slot = None
            else:
                slot = {0: "ledger", 1: "ledger_prev", 2: "ledger_prev2"}.get(off)
            if not slot:
                rep["files"][f.name] = {"slot": "לא בשימוש (הדוח מכסה את השנה)", "year": y}; continue
            r = import_slot(slot, f, TY)
            rep["files"][f.name] = {"slot": slot, "year": r.get("year"), "n": len(r["fields"])}
            rep["notes"] += [f"{f.name}: {n}" for n in r.get("notes", []) if n]
            for k, v in r["fields"].items(): setp(inp, k, v)
        except Exception as e:
            rep["errors"].append(f"{f.name}: {e}")
    rep["input"] = inp
    try:
        res = compute(ClientInput.from_dict(inp)).to_dict(); rep["result"] = res
    except Exception as e:
        rep["errors"].append("חישוב: " + "".join(traceback.format_exception_only(type(e), e)).strip())
    out[d.name] = rep
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, default=str, indent=1)
print("done", len(out))
