"""שורת פקודה.

    python -m trapped_profits run client.json              # דוח מרקדאון
    python -m trapped_profits run client.json --json       # תוצאה מלאה כ-JSON
    python -m trapped_profits run client.xlsx              # קלט ישירות מהאקסל המקורי
    python -m trapped_profits example > client.json        # קובץ קלט לדוגמה (ערכי האקסל)
    python -m trapped_profits batch clients/ --out reports/  # תיקייה שלמה
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import compute
from .models import ClientInput
from .report import render_markdown


def load_input(path: Path) -> ClientInput:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from .excel_io import load_client_from_excel
        return load_client_from_excel(path)
    return ClientInput.from_dict(json.loads(path.read_text(encoding="utf-8")))


def cmd_run(args: argparse.Namespace) -> int:
    res = compute(load_input(Path(args.input)))
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_markdown(res))
    return 0


def cmd_example(args: argparse.Namespace) -> int:
    from .excel_io import load_client_from_excel
    src = Path(__file__).parent.parent / "golden" / "logic_v1.xlsx"
    ci = load_client_from_excel(src)
    ci.data_as_of = "2026-09-28"
    print(json.dumps(ci.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    src, out = Path(args.folder), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(src.iterdir()):
        if f.suffix.lower() not in (".json", ".xlsx"):
            continue
        try:
            res = compute(load_input(f))
        except Exception as e:  # noqa: BLE001 – כשל בלקוח אחד לא עוצר את השאר (תדריך, סעיף 10)
            rows.append({"file": f.name, "error": str(e)})
            continue
        (out / f"{f.stem}.md").write_text(render_markdown(res), encoding="utf-8")
        (out / f"{f.stem}.json").write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({
            "file": f.name, "name": res.name, "overall": res.dashboard.color_overall,
            "status_81": res.dashboard.status_81, "status_62a": res.dashboard.status_62a,
            "surtax": res.calc81.surtax,
            "gap_to_close": res.simulator.gap_to_close if res.simulator.action_required else 0.0,
            "salary_fix_62a": res.s62a.attributed_income, "protected_until": res.dashboard.protected_until,
            "manual_review": len(res.manual_review), "data_as_of": res.data_as_of,
        })
    (out / "_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    order = {"אדום": 0, "צהוב": 1, "ירוק": 2}
    rows_ok = sorted((r for r in rows if "error" not in r), key=lambda r: (order.get(r["overall"], 9), -r["surtax"]))
    print("| לקוח | כולל | תוספת מס | פער לחלוקה | שכר לתיקון 62א | מוגן עד | לבדיקה |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows_ok:
        print(f"| {r['name']} | {r['overall']} | {r['surtax']:,.0f} | {r['gap_to_close']:,.0f} | "
              f"{r['salary_fix_62a']:,.0f} | {r['protected_until']} | {r['manual_review']} |")
    for r in rows:
        if "error" in r:
            print(f"| {r['file']} | שגיאה: {r['error']} | | | | | |")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="trapped_profits", description="מנוע ניטור – חוק הרווחים הכלואים")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="הרצה על לקוח אחד")
    r.add_argument("input")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_run)
    e = sub.add_parser("example", help="קובץ קלט לדוגמה")
    e.set_defaults(fn=cmd_example)
    b = sub.add_parser("batch", help="תיקיית לקוחות → תיקיית דוחות + טבלת סיכום")
    b.add_argument("folder")
    b.add_argument("--out", default="reports")
    b.set_defaults(fn=cmd_batch)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
