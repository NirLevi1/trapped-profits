"""חלון התוכנה (pywebview) + הממשק הקטן שה-HTML קורא לו. המנוע לא נוגע בזה.

הרצה:  python app.py
בנייה לקובץ הרצה בודד:  build.bat
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from trapped_profits.store import ClientStore, app_dir


def ui_path() -> str:
    base = Path(getattr(sys, "_MEIPASS", None) or app_dir())
    return str(base / "ui" / "index.html")


def open_path(path: str) -> None:
    """פותח קובץ/תיקייה בתוכנה המתאימה – ווינדוס, מק או לינוקס."""
    import subprocess
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001 – פתיחה היא נוחות, לא חובה
        pass


class Api:
    def __init__(self) -> None:
        self.store = ClientStore()
        try:
            # אחרי עדכון גרסה: לקוחות שחושבו בלוגיקה ישנה מחושבים מחדש בהפעלה, ומה שזז מסומן "השתנה"
            self.store.recompute_all(only_outdated=True)
        except Exception:  # noqa: BLE001 – לא מפיל את התוכנה; המשתמש יכול "חישוב מחדש לכולם"
            pass

    # ---- read
    def list_clients(self):
        return self.store.list()

    def get_client(self, cid: str):
        return self.store.get(cid)

    # ---- write
    def save_client(self, inp: dict, cid: str | None = None, field_meta: dict | None = None):
        try:
            return self.store.save(inp, cid, field_meta)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def delete_client(self, cid: str):
        return {"ok": self.store.delete(cid)}

    def recompute_all(self):
        return {"n": self.store.recompute_all()}

    def set_handling(self, cid: str, status: str, note: str = ""):
        try:
            return self.store.set_handling(cid, status, note) or {"error": "לקוח לא נמצא"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def get_settings(self):
        from trapped_profits.store import HANDLING_STATUSES
        return {**self.store.settings.load(), "handling_statuses": HANDLING_STATUSES, "data_dir": str(self.store.root)}

    def save_settings(self, data: dict):
        try:
            self.store.settings.save(data)
            n = self.store.recompute_all()          # דגלים השתנו → כולם מחושבים מחדש (החלטה 6)
            return {"ok": True, "recomputed": n}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def set_letter_note(self, cid: str, note: str = ""):
        try:
            return self.store.set_letter_note(cid, note) or {"error": "לקוח לא נמצא"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def approve_fields(self, cid: str, paths=None):
        try:
            return self.store.approve_fields(cid, paths)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def rollover_year(self, cid: str):
        try:
            return self.store.rollover_year(cid)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def revert_field(self, cid: str, path: str):
        try:
            return self.store.revert_field(cid, path)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def revert_today(self, cid: str):
        try:
            return self.store.revert_today(cid)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def apply_import(self, cid: str, fields: dict, sources: dict | None = None, label: str = "קובץ"):
        try:
            return self.store.apply_import(cid, fields, sources, label)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def field_info(self):
        from trapped_profits.store import HUMAN_ONLY_FIELDS
        return {"human_only": HUMAN_ONLY_FIELDS}

    def update_field(self, cid: str, path: str, value=None):
        """עריכת שדה בודד (עודפים במאזן מהתור, דיבידנד שחולק מהסימולטור, שכר בעלים) – שומר ומחשב."""
        try:
            return self.store.update_field(cid, path, value)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def what_if(self, cid: str, extra_dividend: float = 0.0, salary: float = 0.0):
        """סימולציה בכרטיס הלקוח – לא נשמרת."""
        from trapped_profits.engine import what_if
        from trapped_profits.models import ClientInput
        rec = self.store.get(cid)
        if not rec:
            return {"error": "לקוח לא נמצא"}
        try:
            return what_if(ClientInput.from_dict(rec["input"]), float(extra_dividend or 0), float(salary or 0)).to_dict()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # ---- open things
    def export_document(self, cid: str, kind: str = "accountant", fmt: str = "pdf"):
        try:
            p = self.store.export_document(cid, kind, fmt)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if p:
            open_path(str(p))
        return {"path": str(p) if p else None, "fallback_html": bool(p and fmt == "pdf" and p.suffix == ".html")}

    def export_report(self, cid: str):
        p = self.store.export_report(cid)
        if p:
            open_path(str(p))
        return {"path": str(p) if p else None}

    def import_slots(self):
        from trapped_profits.importers import SLOTS
        from trapped_profits.annual_report import ocr_available
        return {"slots": SLOTS, "ocr": bool(ocr_available())}

    def import_file(self, slot: str, tax_year=None, cid: str | None = None, client_name: str = ""):
        """אברהם 20 / משימה 5: בחירת קובץ אחד לחריץ (דוח שנתי / מאזן בוחן / כרטסת) → שדות לטופס, מסומנים לאישור.
        שומר עותק של הקובץ ב-data/files/<לקוח>/<שנה-רבעון>/ (תיעוד)."""
        from trapped_profits.importers import SLOTS, import_slot, keep_copy
        if slot not in SLOTS:
            return {"error": "חריץ לא מוכר"}
        try:
            win = webview.windows[0]
            paths = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=SLOTS[slot]["types"] + ("כל הקבצים (*.*)",))
        except Exception as e:  # noqa: BLE001
            return {"error": f"לא נפתח חלון בחירת קבצים: {e}"}
        if not paths:
            return {"cancelled": True}
        try:
            r = import_slot(slot, paths[0], int(tax_year) if tax_year else None)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "file": Path(paths[0]).name}
        try:
            # לקוח קיים → ישר לתיקייה שלו; לקוח חדש → "_בהמתנה", ובשמירה עובר לתיקיית הלקוח (attach_copies)
            folder = self._client_folder(client_name) if (cid and client_name) else self.store.root.parent / "files" / "_בהמתנה"
            r["saved_copy"] = str(keep_copy(paths[0], folder, SLOTS[slot]["title"]))
        except Exception as e:  # noqa: BLE001
            r.setdefault("notes", []).append(f"לא נשמר עותק של הקובץ: {e}")
        return r

    def _client_folder(self, name: str) -> Path:
        return self.store.root.parent / "files" / self.store.safe_name(name)

    def attach_copies(self, client_name: str, paths: list | None = None):
        """אחרי שמירת לקוח חדש: מעביר את העותקים שהועלו בטופס מ-"_בהמתנה" לתיקיית הלקוח."""
        import shutil
        moved = []
        for p in paths or []:
            src = Path(p)
            if not src.exists() or "_בהמתנה" not in src.parts:
                continue
            dst = self._client_folder(client_name) / src.parent.name / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(str(dst))
        try:
            pend = self.store.root.parent / "files" / "_בהמתנה"
            for d in list(pend.glob("*")):
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            if pend.exists() and not any(pend.iterdir()):
                pend.rmdir()
        except OSError:
            pass
        return {"moved": moved}

    def open_data_folder(self):
        open_path(str(self.store.root.parent))      # data/ – לקוחות, קבצים שהועלו, דוחות
        return True


def main() -> None:
    api = Api()
    webview.create_window("פורטרה · רווחים כלואים", ui_path(), js_api=api, width=1240, height=820, min_size=(900, 600), maximized=True)
    webview.start()


if __name__ == "__main__":
    main()
