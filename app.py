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
    def save_client(self, inp: dict, cid: str | None = None):
        try:
            return self.store.save(inp, cid)
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

    def open_data_folder(self):
        open_path(str(self.store.root))
        return True


def main() -> None:
    api = Api()
    webview.create_window("פורטרה · רווחים כלואים", ui_path(), js_api=api, width=1240, height=820, min_size=(900, 600), maximized=True)
    webview.start()


if __name__ == "__main__":
    main()
