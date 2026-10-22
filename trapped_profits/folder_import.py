"""ייבוא לקוחות מתיקיית איסוף (22.10).

מבנה: <שורש>/<תיקיית לקוח>/<שנה>/<קבצים>
  - "רווח והפסד <שנה>.csv"  – מאזן בוחן לפי חודשים מריווחית
  - "כרטסת <שנה>.xls"       – כרטסת הכנסות מריווחית (טקסט מופרד בטאבים, למרות הסיומת)
  - קובצי PDF               – דוחות שנתיים (לעיתים כמה בתיקייה: חבילה מלאה / חתום / סרוק / טיוטה)
תיקיות שמתחילות ב-"_" (יומנים, דוחות ריצה) וקבצים שלא בתוך תיקיית שנה – לא נקלטים.

אותה פונקציה משמשת את הכפתור בתוכנה ואת הפקודה לסקריפט החילוץ:
    python -m trapped_profits.folder_import "<שורש>" [--tax-year 2026] [--dry-run] [--no-ai]

עקרונות: קובץ שכבר נקלט (אותו תוכן) – מדלגים; ערך שהוקלד ידנית – לא נדרס (נפתחת סתירה לבחירה);
לא עושים מעבר שנה אוטומטי; שגיאה בקובץ אחד לא עוצרת את השאר; בסוף – סיכום.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

YEAR_DIR = re.compile(r"^(20\d\d)$")
TB_NAME = re.compile(r"רווח\s*והפסד\s*(20\d\d)", re.I)
LEDGER_NAME = re.compile(r"כרטסת\s*(20\d\d)", re.I)
# דוחות שנתיים שלא לוקחים: טיוטות, ניירות עבודה, דוחות ביניים, מסמכים שאינם דוח
SKIP_PDF = ("נייר עבודה", "לחתימה", "לא מבוקר", "דף הבהרה", "הנחיות", "ביניים", "טיוטה", "תקציב")


# ---------------------------------------------------------------- עזר

def norm_name(s: str) -> str:
    s = re.sub(r"[֑-ׇ]", "", s or "")
    s = s.replace("״", '"').replace("׳", "'").replace("''", '"')
    s = re.sub(r'בע"?מ|בעמ|בע\'?\'?מ', " ", s)
    s = re.sub(r"[\s\-–,.\"'()_]+", "", s)
    return s


def name_similar(a: str, b: str) -> float:
    """דמיון שמות 0–1 (תווים משותפים ברצף) – לזיהוי לקוח קיים ודוח של חברה אחרת."""
    from difflib import SequenceMatcher
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0 if min(len(a), len(b)) >= 4 else 0.6
    return SequenceMatcher(None, a, b).ratio()


def file_sig(p: Path) -> dict:
    st = p.stat()
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"size": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), "sha1": h.hexdigest()}


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


# ---------------------------------------------------------------- סריקה

def scan_folder(cdir: Path, tax_year: int) -> dict:
    """קבצים של לקוח אחד לפי שנה: {'tb': {שנה: path}, 'ledger': {...}, 'pdf': {שנה: [paths]}, 'ignored': [(path, סיבה)], 'future': [שנים]}"""
    out: dict[str, Any] = {"tb": {}, "ledger": {}, "pdf": {}, "ignored": [], "future": set()}
    for sub in sorted(cdir.iterdir()):
        if sub.is_file():
            out["ignored"].append((sub, "לא בתוך תיקיית שנה"))
            continue
        m = YEAR_DIR.match(sub.name)
        if not m:
            out["ignored"].append((sub, "תיקייה שאינה שנה"))
            continue
        y = int(m.group(1))
        if y > tax_year:
            out["future"].add(y)
        for f in sorted(sub.rglob("*")):
            if not f.is_file() or f.name.startswith(("~$", ".")):
                continue
            ext = f.suffix.lower()
            mt, ml = TB_NAME.search(f.stem), LEDGER_NAME.search(f.stem)
            if ext in (".csv", ".txt", ".xls") and mt:
                out["tb"][int(mt.group(1))] = f
            elif ext in (".csv", ".txt", ".xls") and ml:
                out["ledger"][int(ml.group(1))] = f
            elif ext == ".pdf":
                if any(k in f.stem for k in SKIP_PDF):
                    out["ignored"].append((f, "טיוטה / נייר עבודה / לא מבוקר – לא נקלט"))
                else:
                    out["pdf"].setdefault(y, []).append(f)
            else:
                out["ignored"].append((f, "סוג קובץ לא מוכר"))
    out["future"] = sorted(out["future"])
    return out


def _pdf_order(paths: list[Path]) -> list[Path]:
    """מי קודם: חתום / חבילה מלאה, ואז הקטן (שכבת טקסט – מהיר ומדויק; הגדולים בדרך כלל סרוקים)."""
    def key(p: Path):
        n = p.stem
        pref = 0 if "חתום" in n else 1 if "חבילת דוחות" in n or "דוחות כספיים" in n else 2
        return (pref, p.stat().st_size)
    return sorted(paths, key=key)


def pick_annual_report(files: dict, tax_year: int, folder_name: str, log: list, parse: Callable | None = None) -> tuple[Path | None, dict | None]:
    """הדוח השנתי: השנה האחרונה (עד שנה קודמת) שיש לה דוח שנקרא תקין – שנת הדוח = שם התיקייה ושם החברה תואם."""
    from .importers import import_slot
    parse = parse or (lambda p: import_slot("annual_report", p, tax_year))
    for y in sorted((y for y in files["pdf"] if y <= tax_year - 1), reverse=True):
        for p in _pdf_order(files["pdf"][y]):
            try:
                r = parse(p)
            except Exception as e:  # noqa: BLE001
                log.append(f"{p.name}: לא נקרא – {e}")
                continue
            ry = r.get("year")
            if ry and ry != y:
                log.append(f"{p.name}: דוח לשנת {ry} בתיקיית {y} – לא נלקח")
                continue
            nm = (r.get("fields") or {}).get("structure.name") or ""
            if nm and name_similar(nm, folder_name) < 0.55:
                log.append(f"{p.name}: דוח של \"{nm}\" – לא תואם לתיקייה, לא נלקח")
                continue
            if not (r.get("fields") or {}).get("retained.balance_sheet_retained_earnings") and len(files["pdf"][y]) > 1:
                log.append(f"{p.name}: לא נמצאו עודפים – מנסים קובץ אחר באותה שנה")
                continue
            return p, r
    return None, None


# ---------------------------------------------------------------- תכנון

def plan(root: str | Path, store, tax_year: int, parse_reports: bool = False) -> dict:
    """מה יקרה – בלי לשנות כלום. לכל תיקיית לקוח: לקוח קיים / חדש / לבירור, וקבצים חדשים / שהשתנו / בלי שינוי."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"התיקייה לא נמצאה: {root}")
    recs = [r for r in store.list() if "input" in r]
    by_folder = {((r.get("sync") or {}).get("folder")): r for r in recs if (r.get("sync") or {}).get("folder")}
    items = []
    for cdir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        files = scan_folder(cdir, tax_year)
        it: dict[str, Any] = {"folder": cdir.name, "path": str(cdir), "client_id": None, "client_name": None, "status": "", "files": [], "notes": []}
        rec = by_folder.get(cdir.name)
        if not rec:
            cands = [(name_similar(cdir.name, (r["input"].get("structure") or {}).get("name", "")), r) for r in recs if not (r.get("sync") or {}).get("folder")]
            good = [c for c in cands if c[0] >= 0.85]
            if len(good) == 1:
                rec = good[0][1]
            elif len(good) > 1:
                it["status"] = "לבירור"
                it["notes"].append("מתאים ליותר מלקוח אחד: " + ", ".join((r["input"].get("structure") or {}).get("name", "") for _, r in good))
        if rec:
            it["client_id"], it["client_name"] = rec["id"], (rec["input"].get("structure") or {}).get("name")
        seen = ((rec or {}).get("sync") or {}).get("files") or {}
        wanted = []
        for y, p in files["tb"].items():
            if tax_year - 2 <= y <= tax_year:
                wanted.append(("tb", y, p))
        for y, p in files["ledger"].items():
            if tax_year - 2 <= y <= tax_year:
                wanted.append(("ledger", y, p))
        for y, ps in files["pdf"].items():
            if y > tax_year - 1:
                continue
            for p in ps:
                wanted.append(("pdf", y, p))
        changed = 0
        for kind, y, p in wanted:
            sig = file_sig(p)
            old = seen.get(_rel(root, p))
            st = "new" if not old else ("same" if old.get("sha1") == sig["sha1"] else "changed")
            changed += st != "same"
            it["files"].append({"kind": kind, "year": y, "path": str(p), "rel": _rel(root, p), "name": p.name, "state": st, "sig": sig})
        for p, why in files["ignored"]:
            it["notes"].append(f"{p.name}: {why}")
        if files["future"]:
            it["notes"].append(f"יש קבצים לשנת {', '.join(map(str, files['future']))} – מעבר שנה נעשה ידנית")
        if not it["status"]:
            if not it["files"]:
                it["status"] = "אין קבצים"
            elif not rec:
                it["status"] = "חדש"
            else:
                it["status"] = "לעדכון" if changed else "ללא שינוי"
        items.append(it)
    counts: dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {"root": str(root), "tax_year": tax_year, "items": items, "counts": counts}


# ---------------------------------------------------------------- ביצוע

def _setp(d: dict, k: str, v: Any) -> None:
    ps = k.split(".")
    t = d
    for x in ps[:-1]:
        t = t.setdefault(x, {})
    t[ps[-1]] = v


def _slot_for(kind: str, y: int, tax_year: int, lag: int) -> str | None:
    off = tax_year - y
    if kind == "tb":
        return {0: "trial_balance", 1: "trial_balance_prev", 2: "trial_balance_prev2"}.get(off) if (off == 0 or (off == 1) or (off == 2 and lag >= 3)) else None
    return {0: "ledger", 1: "ledger_prev", 2: "ledger_prev2"}.get(off)


def import_client(item: dict, store, tax_year: int, root: Path, ai_key: str = "", ai_model: str = "", log: Callable[[str], None] = print) -> dict:
    """מבצע לקוח אחד מהתכנון. מחזיר {"client_id","status","imported":[...],"skipped":[...],"errors":[...]}."""
    from .importers import import_slot, keep_copy
    from . import ai_check
    res: dict[str, Any] = {"folder": item["folder"], "client_id": item.get("client_id"), "status": "", "imported": [], "skipped": [], "errors": []}
    todo = [f for f in item["files"] if f["state"] != "same"]
    if not todo:
        res["status"] = "ללא שינוי"
        return res
    rec = store.get(item["client_id"]) if item.get("client_id") else None
    inp = (rec or {}).get("input") or {"structure": {"tax_year": tax_year}}
    ty = int((inp.get("structure") or {}).get("tax_year") or tax_year)
    files_dir = store.root.parent / "files"
    seen = dict(((rec or {}).get("sync") or {}).get("files") or {})

    # 1. דוח שנתי – רק אם אחד מקובצי ה-PDF חדש/השתנה
    pdf_files = {}
    for f in item["files"]:
        if f["kind"] == "pdf":
            pdf_files.setdefault(f["year"], []).append(Path(f["path"]))
    pdf_changed = any(f["kind"] == "pdf" and f["state"] != "same" for f in item["files"])
    lag = max(1, min(3, ty - int((inp.get("structure") or {}).get("last_closed_report_year") or (ty - 1))))
    steps: list[tuple[str, Path, dict]] = []                       # (חריץ, קובץ, תוצאת קריאה)
    if pdf_changed:
        notes: list[str] = []
        p, r = pick_annual_report({"pdf": pdf_files}, ty, item["folder"], notes)
        res["skipped"] += notes
        if p is not None:
            if ai_key:
                ai_check.verify_annual(r, p, ty, ai_key, ai_model or ai_check.DEFAULT_MODEL)
            steps.append(("annual_report", p, r))
            if r.get("year"):
                lag = max(1, min(3, ty - int(r["year"])))
        elif any(y <= ty - 1 for y in pdf_files):
            res["errors"].append("לא נמצא דוח שנתי תקין בתיקיות השנים")
    # 2. רווח והפסד וכרטסות – לפי השנה ביחס לשנת המס
    for f in sorted((f for f in item["files"] if f["kind"] in ("tb", "ledger") and f["state"] != "same"), key=lambda f: (f["kind"] != "tb", -f["year"])):
        slot = _slot_for(f["kind"], f["year"], ty, lag)
        if not slot:
            res["skipped"].append(f"{f['name']}: השנה לא נדרשת (הדוח הסגור מכסה אותה)")
            continue
        try:
            r = import_slot(slot, f["path"], ty)
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"{f['name']}: {e}")
            continue
        if slot == "trial_balance_prev" and lag < 2:
            # הדוח הסגור מכסה את השנה הקודמת – לוקחים רק את השורות (לעונתיות של האומדן), לא את ההוצאות/הגלגול
            r["fields"] = {k: v for k, v in r["fields"].items() if k in ("tb_rows_prev_year", "period_breakdown_prev_year")}
        steps.append((slot, Path(f["path"]), r))

    if not steps:
        for f in todo:
            seen[f["rel"]] = {**f["sig"], "at": datetime.now().isoformat(timespec="seconds"), "used": False}
        if rec:
            rec["sync"] = {"folder": item["folder"], "files": seen}
            store._write(rec["id"], rec)
        res["status"] = "ללא שינוי" if not res["errors"] else "שגיאה"
        return res

    from .importers import SLOTS
    name_for_copy = (inp.get("structure") or {}).get("name") or item["folder"]
    if rec is None:
        # לקוח חדש: כל השדות לטופס, עם מצב "מהקובץ" (לאישור), ושמירה אחת
        meta, sources = {}, []
        now = datetime.now().isoformat(timespec="seconds")
        for slot, p, r in steps:
            for k, v in (r.get("fields") or {}).items():
                _setp(inp, k, v)
                if not k.startswith(("ai_", "tb_rows", "period_breakdown")):
                    meta[k] = {"state": "file", "source": (r.get("sources") or {}).get(k) or f"{SLOTS[slot]['title']} – {p.name}", "at": now}
        st = inp.setdefault("structure", {})
        st["tax_year"] = ty
        if not st.get("name"):
            st["name"] = item["folder"]
            meta["structure.name"] = {"state": "file", "source": "משם התיקייה – לוודא", "at": now}
        name_for_copy = st["name"]
        for slot, p, r in steps:
            try:
                cp = keep_copy(p, files_dir / store.safe_name(name_for_copy), SLOTS[slot]["title"])
            except Exception:  # noqa: BLE001
                cp = p
            sources.append({"slot": slot, "title": SLOTS[slot]["title"], "year": r.get("year"), "file": p.name, "path": str(cp),
                            "fields": len(r.get("fields") or {}), "through_month": (r.get("fields") or {}).get("data_through_month")})
        rec = store.save(inp, None, field_meta=meta, sources=sources)
        store._log(rec, "ייבוא מתיקייה", f"לקוח חדש מתיקיית \"{item['folder']}\": " + ", ".join(p.name for _, p, _ in steps))
        res["status"] = "נוסף"
    else:
        for slot, p, r in steps:
            try:
                cp = keep_copy(p, files_dir / store.safe_name(name_for_copy), SLOTS[slot]["title"])
            except Exception:  # noqa: BLE001
                cp = p
            src = {"slot": slot, "title": SLOTS[slot]["title"], "year": r.get("year"), "file": p.name, "path": str(cp),
                   "fields": len(r.get("fields") or {}), "through_month": (r.get("fields") or {}).get("data_through_month")}
            rec = store.apply_import(rec["id"], r.get("fields") or {}, r.get("sources") or {}, f"ייבוא מתיקייה – {SLOTS[slot]['title']} – {p.name}", source=src, keep_manual=True)
        res["status"] = "עודכן"
    for _, p, _ in steps:
        res["imported"].append(p.name)
    rec = store.get(rec["id"])
    for f in item["files"]:
        if f["state"] != "same" or f["rel"] not in seen:
            seen[f["rel"]] = {**f["sig"], "at": datetime.now().isoformat(timespec="seconds"), "used": any(Path(f["path"]) == p for _, p, _ in steps)}
    rec["sync"] = {"folder": item["folder"], "files": seen, "at": datetime.now().isoformat(timespec="seconds")}
    store._write(rec["id"], rec)
    res["client_id"] = rec["id"]
    return res


class SyncLock:
    """רק סריקה אחת בכל רגע (הכפתור בתוכנה או הסקריפט). נעילה ישנה מ-3 שעות – נחשבת תקועה."""
    def __init__(self, store):
        self.path = store.root / "_sync.lock"

    def __enter__(self):
        if self.path.exists() and time.time() - self.path.stat().st_mtime < 3 * 3600:
            raise RuntimeError("ייבוא מתיקייה כבר רץ (בתוכנה או בסקריפט) – לנסות שוב אחרי שיסתיים")
        self.path.write_text(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}", encoding="utf-8")
        return self

    def __exit__(self, *a):
        try:
            self.path.unlink()
        except Exception:  # noqa: BLE001
            pass


def run(root: str | Path, store, tax_year: int | None = None, ai_key: str = "", ai_model: str = "", dry_run: bool = False,
        progress: Callable[[dict], None] | None = None, review: Callable[[str], None] | None = None, only: list | None = None) -> dict:
    """סריקה + ביצוע. review – מה להריץ על לקוח שהשתנה בסוף (בדיקת היגיון)."""
    tax_year = int(tax_year or store.settings.load().get("default_tax_year") or datetime.now().year)
    pl = plan(root, store, tax_year)
    summary: dict[str, Any] = {"root": str(root), "tax_year": tax_year, "at": datetime.now().isoformat(timespec="seconds"),
                               "plan": pl["counts"], "results": [], "dry_run": dry_run}
    if dry_run:
        summary["items"] = pl["items"]
        return summary
    todo = [it for it in pl["items"] if it["status"] in ("חדש", "לעדכון") and (not only or it["folder"] in only)]
    with SyncLock(store):
        for i, it in enumerate(todo):
            if progress:
                progress({"i": i, "n": len(todo), "folder": it["folder"]})
            try:
                r = import_client(it, store, tax_year, Path(root), ai_key, ai_model)
            except Exception as e:  # noqa: BLE001
                r = {"folder": it["folder"], "status": "שגיאה", "errors": [str(e)], "imported": [], "skipped": []}
            r["notes"] = it["notes"]
            summary["results"].append(r)
            if review and r.get("client_id") and r["status"] in ("נוסף", "עודכן"):
                try:
                    review(r["client_id"])
                except Exception:  # noqa: BLE001
                    pass
    summary["other"] = [{"folder": it["folder"], "status": it["status"], "notes": it["notes"]} for it in pl["items"] if it["status"] in ("לבירור", "אין קבצים")]
    summary["counts"] = {}
    for r in summary["results"]:
        summary["counts"][r["status"]] = summary["counts"].get(r["status"], 0) + 1
    try:
        d = store.root.parent / "sync_reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"ייבוא_{datetime.now():%Y-%m-%d_%H%M}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="ייבוא לקוחות מתיקיית איסוף")
    ap.add_argument("root")
    ap.add_argument("--tax-year", type=int)
    ap.add_argument("--dry-run", action="store_true", help="רק להציג מה יקרה")
    ap.add_argument("--no-ai", action="store_true", help="בלי בודק שני ובלי בדיקת היגיון")
    ap.add_argument("--client", action="append", help="רק תיקיית לקוח מסוימת (אפשר כמה פעמים)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    from .store import ClientStore
    from . import ai_check
    store = ClientStore()
    st = store.settings.load()
    key = "" if a.no_ai else str(st.get("ai_key") or "")
    model = str(st.get("ai_model") or ai_check.DEFAULT_MODEL)

    def review(cid: str) -> None:
        if not key:
            return
        store.review_start(cid)
        try:
            store.review_finish(cid, ai_check.review_client(store.get(cid), key, model))
        except ai_check.AIError as e:
            store.review_finish(cid, error=str(e))

    s = run(a.root, store, a.tax_year, key, model, a.dry_run, progress=lambda p: print(f"[{p['i'] + 1}/{p['n']}] {p['folder']}", flush=True),
            review=review if key else None, only=a.client)
    if a.dry_run:
        for it in s["items"]:
            ch = [f["name"] for f in it["files"] if f["state"] != "same"]
            print(f"{it['status']:10} {it['folder']}" + (f"  ← {', '.join(ch)}" if ch and it["status"] != "ללא שינוי" else ""))
    else:
        for r in s["results"]:
            print(f"{r['status']:8} {r['folder']}" + (f"  ({', '.join(r['imported'])})" if r.get("imported") else "") + (f"  שגיאות: {'; '.join(r['errors'])}" if r.get("errors") else ""))
    print(json.dumps(s.get("counts") or s.get("plan"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
