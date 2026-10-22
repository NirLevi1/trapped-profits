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
        try:
            self.store.backfill_gross_history()          # רווח גולמי של שנות הדוח ללקוחות קיימים – מהדוח השנתי שכבר הועלה
        except Exception:  # noqa: BLE001
            pass
        # 21.10: קורא חדש → קוראים שוב את הדוחות השמורים ברקע (סרוק: עד חצי דקה לדוח); ערך שונה נפתח לבחירה, לא נדרס
        self._reread = {"running": True, "result": None}
        import threading

        def _bg():
            try:
                self._reread["result"] = self.store.reread_reports()
            except Exception as e:  # noqa: BLE001
                self._reread["result"] = {"error": str(e)}
            self._reread["running"] = False
        threading.Thread(target=_bg, daemon=True).start()

    # ---- read
    def list_clients(self):
        return self.store.list()

    def get_client(self, cid: str):
        return self.store.get(cid)

    # ---- write
    def save_client(self, inp: dict, cid: str | None = None, field_meta: dict | None = None, sources: list | None = None):
        try:
            rec = self.store.save(inp, cid, field_meta, sources=sources)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if cid is None or sources:                       # 22.10: לקוח חדש / קבצים חדשים – מבקר אוטומטי ברקע
            rec = self._start_review(rec["id"]) or rec
        return rec

    # ---- 22.10: מבקר – רץ ברקע אחרי שהקבצים בפנים; ממצאים בלבד, לא משנה מספרים
    def _start_review(self, cid: str):
        key, model = self._ai_key()
        if not key:
            return None
        if not hasattr(self, "_reviewing"):
            self._reviewing, self._rerun = set(), set()
        if cid in self._reviewing:
            self._rerun.add(cid)
            return None
        self._reviewing.add(cid)
        rec = self.store.review_start(cid)
        import threading

        def _bg():
            from trapped_profits import ai_check
            try:
                while True:
                    self._rerun.discard(cid)
                    cur = self.store.get(cid)
                    try:
                        r = ai_check.review_client(cur, key, model)
                        self.store.review_finish(cid, r)
                    except ai_check.AIError as e:
                        self.store.review_finish(cid, error=str(e))
                    except Exception as e:  # noqa: BLE001
                        self.store.review_finish(cid, error=f"שגיאה בבדיקה: {e}")
                    if cid not in self._rerun:
                        break
            finally:
                self._reviewing.discard(cid)
        threading.Thread(target=_bg, daemon=True).start()
        return rec

    def review_client(self, cid: str):
        if not self._ai_key()[0]:
            return {"error": "אין מפתח – להגדיר בהגדרות"}
        return self._start_review(cid) or self.store.get(cid)

    def review_mark(self, cid: str, fid: str, state: str):
        try:
            return self.store.review_mark(cid, fid, state)
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
        st = self.store.settings.load()
        key = str(st.pop("ai_key", "") or "")
        # 21.10: המפתח לא חוזר למסך – רק ארבע הספרות האחרונות
        return {**st, "ai_key_tail": key[-4:] if key else "", "handling_statuses": HANDLING_STATUSES, "data_dir": str(self.store.root.parent), "app_version": APP_VERSION}

    def _ai_key(self) -> tuple[str, str]:
        from trapped_profits.ai_check import DEFAULT_MODEL
        st = self.store.settings.load()
        return str(st.get("ai_key") or "").strip(), str(st.get("ai_model") or DEFAULT_MODEL)

    def set_ai_key(self, key: str = "", clear: bool = False):
        """שמירת מפתח הבודק השני (בהגדרות שבתיקיית הנתונים) ובדיקת חיבור."""
        from trapped_profits.ai_check import test_key
        if clear:
            self.store.settings.save({"ai_key": ""})
            return {"ok": True, "msg": "המפתח נמחק – הבדיקה השנייה כבויה", "tail": ""}
        key = (key or "").strip()
        if not key:
            key, model = self._ai_key()
            if not key:
                return {"ok": False, "msg": "אין מפתח"}
            return {**test_key(key, model), "tail": key[-4:]}
        r = test_key(key, self._ai_key()[1])
        if r.get("ok") or "קרדיט" in r.get("msg", ""):
            self.store.settings.save({"ai_key": key, **({"ai_model": r["model"]} if r.get("model") else {})})
            r["tail"] = key[-4:]
        return r

    def reread_status(self):
        st = getattr(self, "_reread", None) or {"running": False, "result": None}
        return {"running": st["running"], "result": st["result"]}

    def resolve_ai(self, cid: str, path: str, choice: str):
        try:
            return self.store.resolve_ai(cid, path, choice)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def resolve_ai_all(self, cid: str, choice: str, reread: bool = True):
        try:
            return self.store.resolve_ai_all(cid, choice, bool(reread))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def resolve_tb_ai(self, cid: str, row_id: str, choice: str):
        try:
            return self.store.resolve_tb_ai(cid, row_id, choice)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def save_settings(self, data: dict):
        try:
            data = {k: v for k, v in (data or {}).items() if k != "ai_key"}     # המפתח נשמר רק דרך set_ai_key
            if "firm_name" in data and not str(data["firm_name"] or "").strip():
                data.pop("firm_name")                                         # 22.10: לא מוחקים את שם המשרד בטעות
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
            rec = self.store.apply_import(cid, fields, sources, label, source=source)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        return self._start_review(cid) or rec           # 22.10: עדכון מקובץ – מבקר ברקע

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
        # 21.10: בודק שני – דוח שנתי בלבד (ניסוי על 7 לקוחות: ברווח והפסד אין תרומה – סוג הכנסה זהה בכולם,
        # ההבדלים רק בשכר תחת "עלויות ייצור" שהוכרע במכוון). בלי מפתח / אינטרנט / קרדיט: ממשיכים, עם הודעה
        if slot == "annual_report":
            from trapped_profits import ai_check
            key, model = self._ai_key()
            if not key:
                r.setdefault("notes", []).append("בודק שני כבוי (אין מפתח בהגדרות) – הערכים מהקורא שלנו בלבד")
                r["ai"] = {"ok": False, "msg": "אין מפתח", "off": True}
            elif slot == "annual_report":
                ai_check.verify_annual(r, paths[0], int(tax_year) if tax_year else None, key, model)
            else:
                ai_check.verify_tb(r, key, model)
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
            r = subprocess.run([exe, *args], cwd=str(root), capture_output=True, stdin=subprocess.DEVNULL, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=env, **kw)        # הודעות עדכון בעברית
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
        ver = None
        try:
            import re as _re
            m = _re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (app_dir() / "trapped_profits" / "__init__.py").read_text(encoding="utf-8"))
            ver = m.group(1) if m else None
        except Exception:  # noqa: BLE001
            pass
        self._restart()
        return {"ok": True, "version": ver}

    @staticmethod
    def _restart():
        """22.10: סוגר את התוכנה ומפעיל מחדש (run.bat מוסתר). תמיד יוצאים – גם אם ההפעלה מחדש נכשלה (נרשם ב-update.log)."""
        import subprocess
        import threading
        root = app_dir()

        def log(msg: str) -> None:
            try:
                with open(root / "update.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} restart: {msg}\n")
            except Exception:  # noqa: BLE001
                pass

        def go():
            import time
            time.sleep(0.8)
            try:
                if sys.platform.startswith("win"):
                    subprocess.Popen(["cmd", "/c", str(root / "run.bat")], cwd=str(root), creationflags=0x08000000,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
                else:
                    subprocess.Popen(["/bin/bash", str(root / "run.command")], cwd=str(root))
                log("launched")
            except Exception as e:  # noqa: BLE001
                log(f"launch failed: {e}")
            finally:
                log(f"exit pid {os.getpid()}")      # 22.10: בלי destroy לחלון (נתקע מחוץ לתהליך הראשי) – יציאה ישירה
                os._exit(0)
        threading.Thread(target=go, daemon=True).start()

    def restart_app(self):
        self._restart()
        return {"ok": True}

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

    def approve_tb(self, cid: str, undo: bool = False):
        try:
            return self.store.approve_tb(cid, bool(undo))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def set_tb_cogs(self, cid: str, row_id: str, on: bool):
        try:
            return self.store.set_tb_cogs(cid, str(row_id), bool(on))
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

    # ---- 22.10: ייבוא לקוחות מתיקיית איסוף
    def choose_intake_folder(self):
        try:
            win = webview.windows[0]
            cur = self.store.settings.load().get("intake_dir") or str(Path.home())
            paths = win.create_file_dialog(webview.FOLDER_DIALOG, directory=cur)
        except Exception as e:  # noqa: BLE001
            return {"error": f"לא נפתח חלון בחירת תיקייה: {e}"}
        if not paths:
            return {"cancelled": True}
        self.store.settings.save({"intake_dir": str(paths[0])})
        return {"intake_dir": str(paths[0])}

    def intake_plan(self):
        from trapped_profits import folder_import as fi
        root = self.store.settings.load().get("intake_dir")
        if not root:
            return {"error": "לא נבחרה תיקיית איסוף"}
        try:
            pl = fi.plan(root, self.store, int(self.store.settings.load().get("default_tax_year") or 2026))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        for it in pl["items"]:
            for f in it["files"]:
                f.pop("sig", None)
        return pl

    def intake_run(self, only=None):
        from trapped_profits import folder_import as fi, ai_check
        st = getattr(self, "_intake", None)
        if st and st.get("running"):
            return {"error": "ייבוא כבר רץ"}
        root = self.store.settings.load().get("intake_dir")
        if not root:
            return {"error": "לא נבחרה תיקיית איסוף"}
        key, model = self._ai_key()
        self._intake = {"running": True, "progress": None, "summary": None, "error": None}
        import threading

        def _bg():
            try:
                done: list[str] = []
                s = fi.run(root, self.store, None, key, model, progress=lambda p: self._intake.update(progress=p),
                           review=(lambda cid: done.append(cid)) if key else None, only=only or None)
                self._intake["summary"] = s
                for i, cid in enumerate(done):                    # בדיקת היגיון – בסוף, לקוח אחרי לקוח
                    self._intake["progress"] = {"i": i, "n": len(done), "folder": "בדיקת היגיון", "review": True}
                    self.store.review_start(cid)
                    try:
                        self.store.review_finish(cid, ai_check.review_client(self.store.get(cid), key, model))
                    except ai_check.AIError as e:
                        self.store.review_finish(cid, error=str(e))
                    except Exception as e:  # noqa: BLE001
                        self.store.review_finish(cid, error=f"שגיאה בבדיקה: {e}")
            except Exception as e:  # noqa: BLE001
                self._intake["error"] = str(e)
            self._intake["running"] = False
        threading.Thread(target=_bg, daemon=True).start()
        return {"ok": True}

    def intake_status(self):
        st = getattr(self, "_intake", None) or {"running": False}
        return {k: st.get(k) for k in ("running", "progress", "summary", "error")}

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
        # 22.10: שם המשרד, רואה החשבון ומפתח הבודק השני עוברים לתיקייה החדשה (אם אין בה כבר)
        old_st = self.store.settings.load()
        set_data_root(new)
        self.store = ClientStore(new / "clients")
        try:
            import json as _json
            cur = _json.loads(self.store.settings.path.read_text(encoding="utf-8")) if self.store.settings.path.exists() else {}
        except Exception:  # noqa: BLE001
            cur = {}
        carry = {k: old_st.get(k) for k in ("firm_name", "accountant_name", "ai_key", "ai_model", "intake_dir") if old_st.get(k) and not str(cur.get(k) or "").strip()}
        if carry:
            self.store.settings.save(carry)
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


def _single_instance() -> None:
    """22.10: מופע אחד בלבד – מופע ישן שנשאר פתוח (למשל אחרי עדכון) נסגר כשהחדש עולה."""
    pidf = app_dir() / "app.pid"
    try:
        old = int(pidf.read_text().strip()) if pidf.exists() else 0
    except Exception:  # noqa: BLE001
        old = 0
    if old and old != os.getpid() and sys.platform.startswith("win"):
        import subprocess
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {old}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 creationflags=0x08000000, timeout=10).stdout.lower()
            if "python" in out:
                subprocess.run(["taskkill", "/PID", str(old), "/F"], capture_output=True, creationflags=0x08000000, timeout=10)
        except Exception:  # noqa: BLE001
            pass
    # כל חלון של התוכנה שעדיין פתוח (מכל תהליך אחר) – נסגר. גיבוי לקובץ ה-pid
    if sys.platform.startswith("win"):
        try:
            import ctypes
            import subprocess
            u = ctypes.windll.user32
            for _ in range(6):
                hwnd = u.FindWindowW(None, WINDOW_TITLE)
                if not hwnd:
                    break
                pid = ctypes.c_ulong()
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value or pid.value == os.getpid():
                    break
                subprocess.run(["taskkill", "/PID", str(pid.value), "/F"], capture_output=True, creationflags=0x08000000, timeout=10)
                import time
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
    try:
        pidf.write_text(str(os.getpid()))
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _single_instance()
    set_app_id()
    set_app_name()
    api = Api()
    window = webview.create_window(WINDOW_TITLE, ui_path(), js_api=api, width=1240, height=820, min_size=(900, 600), maximized=True)
    window.events.shown += lambda: set_app_icon(window)
    webview.start()


if __name__ == "__main__":
    main()
