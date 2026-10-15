"""חלון התוכנה (pywebview) + הממשק הקטן שה-HTML קורא לו. המנוע לא נוגע בזה.

הרצה:  python app.py
בנייה לקובץ הרצה בודד:  build.bat
"""

from __future__ import annotations

import os
from datetime import datetime
import sys
from pathlib import Path

import webview

from trapped_profits import APP_VERSION
from trapped_profits.store import ClientStore, app_dir, data_root, set_data_root


def icon_path(ext: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", None) or app_dir())
    return str(base / "assets" / f"icon.{ext}")


def set_app_icon(window=None) -> None:
    """אייקון ה-F של פורטרה: בדוק (מק) / בשורת המשימות (ווינדוס). נוחות בלבד – כישלון לא מפיל."""
    try:
        if sys.platform == "darwin":
            from AppKit import NSApplication, NSImage  # type: ignore[import-not-found]  # pyobjc – מגיע עם pywebview במק
            img = NSImage.alloc().initWithContentsOfFile_(icon_path("png"))
            if img:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        elif sys.platform.startswith("win"):
            import ctypes
            # 1. הדרך הישירה: חלון ה-.NET של pywebview – האייקון בכותרת ובשורת המשימות
            try:
                native = getattr(window, "native", None)
                if native is not None:
                    import clr  # type: ignore[import-not-found]  # pythonnet – מגיע עם pywebview בווינדוס
                    clr.AddReference("System.Drawing")
                    from System.Drawing import Icon  # type: ignore[import-not-found]
                    native.Icon = Icon(icon_path("ico"))
            except Exception:  # noqa: BLE001
                pass
            # 2. גיבוי: הודעת WM_SETICON לחלון לפי הכותרת
            hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                for which, size in ((0, 16), (1, 32)):          # ICON_SMALL, ICON_BIG
                    hicon = ctypes.windll.user32.LoadImageW(None, icon_path("ico"), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                    if hicon:
                        ctypes.windll.user32.SendMessageW(hwnd, 0x80, which, hicon)     # WM_SETICON
    except Exception:  # noqa: BLE001
        pass


WINDOW_TITLE = "פורטרה · רווחים כלואים"


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
    def save_client(self, inp: dict, cid: str | None = None, field_meta: dict | None = None, sources: list | None = None):
        try:
            return self.store.save(inp, cid, field_meta, sources=sources)
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
        return {**self.store.settings.load(), "handling_statuses": HANDLING_STATUSES, "data_dir": str(self.store.root.parent), "app_version": APP_VERSION}

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

    def apply_import(self, cid: str, fields: dict, sources: dict | None = None, label: str = "קובץ", source: dict | None = None):
        try:
            return self.store.apply_import(cid, fields, sources, label, source=source)
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
        # סבב 3: רשומת מקור – מה הועלה, מתי, כמה שדות, עד איזה חודש – לרשימת "מקורות" בכרטיס ולסימון "נבדק"
        r["source"] = {"slot": slot, "title": SLOTS[slot]["title"], "year": r.get("year"), "file": Path(paths[0]).name,
                       "path": r.get("saved_copy") or str(paths[0]), "fields": len(r.get("fields") or {}),
                       "through_month": (r.get("fields") or {}).get("data_through_month")}
        return r

    def _client_folder(self, name: str) -> Path:
        return self.store.root.parent / "files" / self.store.safe_name(name)

    def attach_copies(self, client_name: str, paths: list | None = None, cid: str | None = None):
        """אחרי שמירת לקוח חדש: מעביר את העותקים שהועלו בטופס מ-"_בהמתנה" לתיקיית הלקוח (ומעדכן את רשומות המקור)."""
        import shutil
        moved = []
        remap = {}
        for p in paths or []:
            src = Path(p)
            if not src.exists() or "_בהמתנה" not in src.parts:
                continue
            dst = self._client_folder(client_name) / src.parent.name / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(str(dst))
            remap[str(src)] = str(dst)
        if cid and remap:
            rec = self.store.get(cid)
            if rec:
                for sr in rec.get("sources") or []:
                    if sr.get("path") in remap:
                        sr["path"] = remap[sr["path"]]
                self.store._write(cid, rec)
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

    # ---- עדכונים מרחוק (ניר דוחף לגיטהאב → אצל אברהם "עדכון והפעלה מחדש")
    @staticmethod
    def _git_exe() -> str | None:
        """איפה גיט: בנתיב, או במקומות המוכרים בווינדוס (אחרי התקנה טרייה הנתיב של המערכת עוד לא תמיד מעודכן בתוכנה שרצה)."""
        import shutil
        g = shutil.which("git")
        if g:
            return g
        if sys.platform.startswith("win"):
            for c in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
                      Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "cmd" / "git.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe"):
                if c.exists():
                    return str(c)
        return None

    def _git(self, *args, timeout=25):
        import subprocess
        root = app_dir()
        if not (root / ".git").exists():
            return None
        exe = self._git_exe()
        log = root / "update.log"
        if not exe:
            log.open("a", encoding="utf-8").write(f"{datetime.now():%d.%m.%Y %H:%M:%S} git not found (PATH={os.environ.get('PATH','')[:300]})\n")
            return None
        try:
            kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}   # בלי חלון שחור
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}   # לא לתקוע על חלון סיסמה – המפתח בכתובת המאגר
            r = subprocess.run([exe, *args], cwd=str(root), capture_output=True, text=True, timeout=timeout, env=env, **kw)
            log.open("a", encoding="utf-8").write(f"{datetime.now():%d.%m.%Y %H:%M:%S} git {' '.join(args)} -> {r.returncode} {(r.stderr or r.stdout).strip()[-200:]}\n")
            return r
        except Exception as e:  # noqa: BLE001 – אין גיט / אין רשת
            log.open("a", encoding="utf-8").write(f"{datetime.now():%d.%m.%Y %H:%M:%S} git {' '.join(args)} failed: {e}\n")
            return None

    def check_update(self):
        """כמה גרסאות אחורה אנחנו מול גיטהאב. {"behind": n, "notes": [...]} ; {"behind": 0}; {"unavailable": סיבה}."""
        if not (app_dir() / ".git").exists():
            return {"unavailable": "התוכנה לא הותקנה מגיטהאב – עדכון ידני"}
        if not self._git_exe():
            return {"unavailable": "גיט לא נמצא במחשב – להפעיל מחדש את המחשב אחרי ההתקנה, או להריץ update.bat"}
        r = self._git("fetch", "--quiet", timeout=30)
        if r is None or r.returncode != 0:
            return {"unavailable": "אין חיבור לגיטהאב כרגע" + (f" ({(r.stderr or '').strip()[-120:]})" if r is not None and (r.stderr or '').strip() else "")}
        br = self._git("rev-parse", "--abbrev-ref", "HEAD")
        branch = (br.stdout.strip() if br and br.returncode == 0 else "main") or "main"
        c = self._git("rev-list", "--count", f"HEAD..origin/{branch}")
        n = int(c.stdout.strip() or 0) if c and c.returncode == 0 else 0
        notes = []
        if n:
            lg = self._git("log", "--format=%s", f"HEAD..origin/{branch}")
            notes = [x for x in (lg.stdout.splitlines() if lg else []) if x][:8]
        return {"behind": n, "notes": notes, "version": APP_VERSION}

    def apply_update(self):
        """מושך את הגרסה האחרונה ומפעיל מחדש. הנתונים (data/) לא בגיט ולא נוגעים בהם."""
        r = self._git("pull", "--ff-only", timeout=90)
        if r is None or r.returncode != 0:
            return {"error": "העדכון נכשל: " + ((r.stderr or r.stdout).strip()[-300:] if r else "אין גיט/רשת")}
        self._restart()
        return {"ok": True}

    @staticmethod
    def _restart():
        import subprocess
        import threading
        root = app_dir()

        def go():
            import time
            time.sleep(0.8)
            if sys.platform.startswith("win"):
                subprocess.Popen(["cmd", "/c", "start", "", str(root / "run.bat")], cwd=str(root), creationflags=0x08000000)
            else:
                subprocess.Popen(["/bin/bash", str(root / "run.command")], cwd=str(root))
            os._exit(0)
        threading.Thread(target=go, daemon=True).start()

    def open_source(self, cid: str, index: int):
        """פתיחת הקובץ המקורי שהועלה (PDF בקורא, קובץ ריווחית באקסל)."""
        rec = self.store.get(cid)
        srcs = (rec or {}).get("sources") or []
        if not (0 <= int(index) < len(srcs)):
            return {"error": "קובץ לא נמצא"}
        p = Path(srcs[int(index)].get("path") or "")
        if not p.exists():
            return {"error": f"הקובץ לא נמצא בדיסק: {p.name}"}
        open_path(str(p))
        return {"ok": True}

    def adjust(self, cid: str, key: str, month=None, kind: str = "accepted", amount: float = 0.0, note: str = ""):
        try:
            return self.store.adjust(cid, key, month, kind, amount, note)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def mark_reviewed(self, cid: str, index: int, accept_pending: bool = False):
        try:
            return self.store.mark_reviewed(cid, int(index), bool(accept_pending))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def open_data_folder(self):
        open_path(str(self.store.root.parent))      # data/ – לקוחות, קבצים שהועלו, דוחות
        return True

    def choose_data_folder(self):
        """הגדרות: בחירת תיקיית נתונים אחרת (למשל כונן משותף במשרד). נכנסת לתוקף מיד; הקבצים הקיימים לא מועברים."""
        try:
            win = webview.windows[0]
            paths = win.create_file_dialog(webview.FOLDER_DIALOG, directory=str(self.store.root.parent))
        except Exception as e:  # noqa: BLE001
            return {"error": f"לא נפתח חלון בחירת תיקייה: {e}"}
        if not paths:
            return {"cancelled": True}
        new = Path(paths[0])
        set_data_root(new)
        self.store = ClientStore(new / "clients")
        return {"data_dir": str(new), "clients": len(self.store.list())}


def set_app_id() -> None:
    """ווינדוס: מזהה יישום משלנו – כך שורת המשימות לא מקבצת אותנו עם פייתון ומציגה את אייקון החלון (F) ולא את של pythonw."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Fortera.TrappedProfits")
        except Exception:  # noqa: BLE001
            pass


def set_app_name() -> None:
    """במק התהליך הוא פייתון – ולכן בשורת התפריטים ובדוק כתוב "Python". משנים את שם החבילה בזיכרון לפני שהחלון עולה."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle  # type: ignore[import-not-found]
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "פורטרה"
            info["CFBundleDisplayName"] = "פורטרה"
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    set_app_id()
    set_app_name()
    api = Api()
    window = webview.create_window(WINDOW_TITLE, ui_path(), js_api=api, width=1240, height=820, min_size=(900, 600), maximized=True)
    window.events.shown += lambda: set_app_icon(window)
    webview.start()


if __name__ == "__main__":
    main()
