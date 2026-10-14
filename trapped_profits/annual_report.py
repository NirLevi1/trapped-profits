"""קריאת הדוח השנתי הסגור (PDF) → שדות לטופס. משימה פתוחה 5 / הערת אברהם 20.

עובד על PDF דיגיטלי (שכבת טקסט) ועל PDF סרוק (זיהוי תווים: טסרקט – עברית לתוויות, אנגלית למספרים,
ומיזוג לפי מיקום בעמוד). כל שדה שנמצא מוחזר עם השורה שממנה נקרא – לאישור. מה שלא נמצא – לא מוחזר.

שדות:
  structure.name, structure.last_closed_report_year
  retained.balance_sheet_retained_earnings      – "רווח (הפסד) שנצבר" / "עודפים" / "יתרת רווח" במאזן, עמודת השנה
  distributions.retained_at_start_day            – אותה שורה, עמודת השנה הקודמת (רק אם שנת הדוח 2025 → יתרה ל-1.1.2025)
  shields.share_capital_and_premium              – "הון מניות" (+ "פרמיה")
  shields.special_loans_deposits_cash            – "מזומנים ושווי מזומנים" (+ "פיקדונות")
  shields.expenses_prev_year / expenses_prev2_year – סכום שורות ההוצאות בדוח רווח והפסד, שתי העמודות
  distributions.dividend_in_determining_period   – "ייעוד רווחים" / "דיבידנד" בשנת 2025
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HEB = re.compile(r"[\u05d0-\u05ea]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def _n(t: str) -> str:
    """נורמליזציה להשוואה: אותיות סופיות → רגילות (מאזן/מאזנים, שנצבר/שנצברו)."""
    return t.translate(_FINALS)


def _has(text: str, *keys: str) -> bool:
    t = _n(text)
    return any(_n(k) in t for k in keys)
_NUMTOK = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?\)?$")
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


def tessdata_dir() -> Path:
    from .store import app_dir
    return app_dir() / "vendor" / "tessdata"


def ocr_available() -> str | None:
    """נתיב לטסרקט, או None אם לא מותקן."""
    from .store import app_dir
    portable = app_dir() / "tesseract"                     # תיקייה ניידת ליד התוכנה (כמו בממיין החשבוניות)
    for c in (str(portable / "tesseract.exe"), str(portable / "tesseract"), "tesseract",
              r"C:\Program Files\Tesseract-OCR\tesseract.exe", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return None


# ---------------------------------------------------------------------------
# מילים עם מיקום – מהשכבה הדיגיטלית או מזיהוי תווים
# ---------------------------------------------------------------------------
def _tsv_words(tess: str, png: Path, lang: str) -> list[Word]:
    env = {**os.environ, "TESSDATA_PREFIX": str(tessdata_dir()), "OMP_THREAD_LIMIT": "1"}
    out = subprocess.run([tess, str(png), "-", "-l", lang, "--psm", "6", "tsv"], capture_output=True, text=True, env=env, timeout=180)
    if out.returncode != 0:
        raise RuntimeError("טסרקט נכשל: " + out.stderr[-300:])
    words = []
    for line in out.stdout.splitlines()[1:]:
        c = line.split("\t")
        if len(c) < 12 or c[11].strip() == "":
            continue
        x, y, w, h = map(float, c[6:10])
        words.append(Word(x, y, x + w, y + h, c[11].strip()))
    return words


_COMMON = ("הוצאות", "הכנסות", "מאזן", "רווח", "הון", "מניות", "ליום", "בדצמבר", "מזומנים", "לקוחות", "ספקים", "שנצבר", "הפסד")


def _fix_reversed(ws: list[Word]) -> list[Word]:
    """יש מחוללי PDF ששומרים אותיות עבריות בסדר הפוך (ויזואלי). אם רוב המילים המוכרות מופיעות הפוכות – הופכים."""
    straight = sum(1 for w in ws for k in _COMMON if _n(k) in _n(w.text))
    flipped = sum(1 for w in ws for k in _COMMON if _n(k)[::-1] in _n(w.text))
    if flipped > straight:
        # גם סדר המילים הפוך (ויזואלי = שמאל→ימין), לכן משקפים את ה-x של המילים העבריות כדי שהתווית תיקרא נכון
        W = max((w.x1 for w in ws), default=0.0)
        return [Word(W - w.x1, w.y0, W - w.x0, w.y1, w.text[::-1]) if _HEB.search(w.text) else w for w in ws]
    return ws


def _text_layer_ok(ws: list[Word]) -> bool:
    """שכבת טקסט טובה = יש שורות עם תווית עברית מוכרת ומספר מעוצב (1,234). סורקים שמוסיפים שכבת זיהוי גרועה
    נותנים תוויות שבורות ומספרים בלי פסיקים – ואז עדיף הזיהוי שלנו."""
    if sum(1 for w in ws if _HEB.search(w.text)) < 5:
        return False
    nums = [w for w in ws if _NUMTOK.match(w.text)]
    if len(nums) < 4:
        return True                     # עמוד טקסטואלי (חוות דעת, באורים) – אין מה לשפר
    good = sum(1 for w in nums if "," in w.text)
    labels = sum(1 for w in ws if _HEB.search(w.text) and len(w.text) >= 3 and _has(w.text, *_COMMON))
    return good >= max(2, len(nums) // 4) and labels >= 2


def page_words(pdf: str | Path) -> list[list[Word]]:
    import pymupdf
    doc = pymupdf.open(str(pdf))
    pages: list[list[Word]] = []
    tess = None
    tmp = None
    for i, page in enumerate(doc):
        ws = _fix_reversed([Word(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")])
        if _text_layer_ok(ws) or not (tess or ocr_available()):
            pages.append(ws)
            continue
        # סרוק → זיהוי תווים
        tess = tess or ocr_available()
        if not tess:
            pages.append([])
            continue
        tmp = tmp or Path(tempfile.mkdtemp())
        png = tmp / f"p{i + 1}.png"
        page.get_pixmap(dpi=220).save(str(png))
        heb = [w for w in _tsv_words(tess, png, "heb") if _HEB.search(w.text)]
        txt = " ".join(w.text for w in heb)
        if not _has(txt, "מאזן", "והפסד", "בדצמבר", "הון מניות"):
            pages.append(heb)                       # עמוד לא רלוונטי – בלי זיהוי מספרים
            continue
        eng = [w for w in _tsv_words(tess, png, "eng") if _NUMTOK.match(w.text)]
        pages.append(heb + eng)
    return pages


def group_lines(words: list[Word]) -> list[list[Word]]:
    """קיבוץ מילים לשורות לפי גובה (סובלנות: חצי גובה אות)."""
    if not words:
        return []
    hs = sorted(w.y1 - w.y0 for w in words)
    tol = max(2.0, hs[len(hs) // 2] * 0.6)
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.yc):
        if lines and abs(lines[-1][0].yc - w.yc) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w.x0) for l in lines]


def _num(tok: str) -> float | None:
    t = tok.strip()
    if not _NUMTOK.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-")
    v = float(t.strip("()-").replace(",", ""))
    return -v if neg else v


def _label(line: list[Word]) -> str:
    """התווית העברית של השורה – מימין לשמאל (המילים ממוינות לפי x עולה, לכן הופכים)."""
    return " ".join(w.text for w in sorted(line, key=lambda w: -w.x0) if _HEB.search(w.text))


def _numbers(line: list[Word]) -> list[tuple[float, float]]:
    """[(x-מרכז, ערך)] – בלי מספרי באור (ספרה אחת-שתיים בלי פסיק) ובלי שנים."""
    out = []
    for w in line:
        v = _num(w.text)
        if v is None or _YEAR.match(w.text):
            continue
        if "," not in w.text and abs(v) < 100:        # מספר באור / מספר עמוד
            continue
        out.append((w.xc, v))
    return out


# ---------------------------------------------------------------------------
# פענוח
# ---------------------------------------------------------------------------
_RETAINED = ("שנצבר", "עודפים", "יתרת רווח", "רווחים שנצברו", "עודפים שנצברו")
_RETAINED_SKIP = ("לתחילת", "תחילת השנה", "עוברת")      # שורות רווח והפסד שאינן היתרה במאזן
_EXPENSE = ("הוצאות הנהלה", "הוצאות מכירה", "עלות המכירות", "עלות המכר", "הוצאות מימון", "הוצאות שיווק", "עלות ההכנסות", "הוצאות תפעול", "הוצאות אחרות")
_SKIP = ("סה\"כ", "סהכ", "רווח", "לאחר", "לפני")


class _Page:
    def __init__(self, lines: list[list[Word]]):
        self.lines = lines
        self.text = "\n".join(_label(l) for l in lines)
        # עמודות השנים: שורה עם שתי שנים → x של כל שנה
        self.year_cols: dict[int, float] = {}
        for l in lines:
            ys = [(w.xc, int(w.text)) for w in l if _YEAR.match(w.text)]
            if len(ys) >= 2:
                self.year_cols = {y: x for x, y in ys}
                break

    def value(self, label_keys: tuple[str, ...], year: int) -> tuple[float | None, str]:
        """הערך בעמודת השנה בשורה הראשונה שהתווית שלה מכילה אחת מהמילים."""
        for l in self.lines:
            lab = _label(l)
            if _has(lab, *label_keys) and not (label_keys is _RETAINED and _has(lab, *_RETAINED_SKIP)):
                nums = _numbers(l)
                if not nums:
                    continue
                return self._pick(nums, year), lab
        return None, ""

    def _pick(self, nums: list[tuple[float, float]], year: int) -> float | None:
        if year in self.year_cols and len(self.year_cols) >= 2:
            x = self.year_cols[year]
            return min(nums, key=lambda n: abs(n[0] - x))[1]
        # בלי כותרת שנים: בעברית העמודה של השנה הנוכחית היא הימנית
        return max(nums, key=lambda n: n[0])[1]

    def sum_rows(self, keys: tuple[str, ...], year: int) -> tuple[float, list[str]]:
        total, used = 0.0, []
        for l in self.lines:
            lab = _label(l)
            if _has(lab, *keys) and not _has(lab, *_SKIP):
                nums = _numbers(l)
                if nums:
                    v = self._pick(nums, year)
                    if v is not None:
                        total += abs(v)
                        used.append(f"{lab}: {v:,.0f}")
        return total, used


def parse_annual_report(pdf: str | Path) -> dict[str, Any]:
    pages = page_words(pdf)
    if not any(pages):
        if not ocr_available():
            raise RuntimeError("ה-PDF סרוק ואין זיהוי תווים מותקן (ווינדוס: winget install UB-Mannheim.TesseractOCR; מק: brew install tesseract)")
        raise RuntimeError("לא נמצא טקסט ב-PDF")
    P = [_Page(group_lines(ws)) for ws in pages]
    base_fields: dict[str, Any] = {}
    notes: list[str] = []
    src: dict[str, str] = {}

    # שם ושנת הדוח – מהעמוד הראשון עם "בע"מ" ו"בדצמבר"
    year = None
    for pg in P:
        m = re.search(r"(20\d{2})", " ".join(w.text for l in pg.lines for w in l if _YEAR.match(w.text)) or "")
        if _has(pg.text, "בדצמבר") and m:
            ys = [int(w.text) for l in pg.lines for w in l if _YEAR.match(w.text)]
            year = max(ys) if ys else None
            break
    for pg in P:
        for l in pg.lines:
            lab = _label(l)
            if 2 <= len(lab.split()) <= 7 and re.search(r"בע[\"'׳״]*\s?מ(\s|$)", lab):
                nm = re.sub(r"[\u0591-\u05c7]", "", lab)                 # בלי ניקוד שזיהוי התווים ממציא
                nm = re.sub(r"בע[\"'׳״]*\s?מ(?=\s|$)", 'בע"מ', nm)
                base_fields["structure.name"] = re.sub(r"\s+", " ", nm).strip()
                break
        if "structure.name" in base_fields:
            break
    if year:
        base_fields["structure.last_closed_report_year"] = year
        notes.append(f"דוח ליום 31.12.{year}")
    else:
        notes.append("לא זוהתה שנת הדוח – לבדוק")
        year = 0

    # ערכים לפי שנה (עמודת הדוח ועמודת השנה הקודמת) – המיפוי לשדות תלוי בשנת המס, ראו map_annual_fields
    by_year: dict[str, dict[int, float]] = {"retained": {}, "expenses": {}, "dividend": {}, "cash": {}, "capital": {}}
    prev_year = year - 1 if year else 0

    # מאזן
    bs = next((pg for pg in P if _has(pg.text, "מאזן") and _has(pg.text, "נכסים", "התחייבויות", "הון מניות")
               and _has(pg.text, *_RETAINED)), None)
    if bs:
        for y in (year, prev_year):
            if not y or (y != year and len(bs.year_cols) < 2):
                continue
            v, lab = bs.value(_RETAINED, y)
            if v is not None:
                by_year["retained"][y] = v
                src.setdefault("retained", lab)
            v, lab = bs.value(("הון מניות",), y)
            if v is not None:
                prem, _ = bs.value(("פרמיה",), y)
                by_year["capital"][y] = v + (prem or 0)
                src.setdefault("capital", lab)
            v, lab = bs.value(("מזומנים", "מזומניס"), y)
            if v is not None:
                dep, _ = bs.value(("פיקדונות", "פקדונות"), y)
                by_year["cash"][y] = v + (dep or 0)
                src.setdefault("cash", lab)
    else:
        notes.append("לא זוהה עמוד מאזן")

    # רווח והפסד
    pl = next((pg for pg in P if _has(pg.text, "והפסד") and _has(pg.text, "הוצאות") and not _has(pg.text[:200], "מאזן")), None)
    if pl:
        for y in (year, prev_year):
            if not y or (y != year and len(pl.year_cols) < 2):
                continue
            tot, used = pl.sum_rows(_EXPENSE, y)
            if used:
                by_year["expenses"][y] = tot
                src.setdefault(f"expenses_{y}", "; ".join(used))
            v, lab = pl.value(("ייעוד רווחים", "דיבידנד", "דיווידנד"), y)
            if v is not None:
                by_year["dividend"][y] = abs(v)
                src.setdefault("dividend", lab)
        notes.append("הוצאות כוללות פחת – אם יש פחת על נכסים מיוחדים, להפחית ידנית")
    else:
        notes.append("לא זוהה עמוד רווח והפסד")

    raw_src = dict(src)
    fields, src = map_annual_fields(by_year, year, None, raw_src, notes)
    fields.update(base_fields)
    return {"kind": "annual_report", "year": year or None, "fields": fields, "sources": src, "notes": notes,
            "by_year": {k: {str(y): v for y, v in d.items()} for k, d in by_year.items()}, "raw_sources": raw_src,
            "ocr": ocr_available() is not None}


def map_annual_fields(by_year: dict, report_year: int, tax_year: int | None, raw_src: dict, notes: list[str]) -> tuple[dict, dict]:
    """ממפה ערכים-לפי-שנה לשדות הטופס לפי שנת המס הנבדקת.

    tax_year = report_year + 1 (הרגיל, תרחיש א׳): עודפים → בסיס; הוצאות הדוח → שנה קודמת, העמודה הקודמת → שנתיים.
    tax_year = report_year + 2 (דוח ישן בשנה, תרחיש ב׳): עודפי הדוח → בסיס כאומדן (אברהם מגלגל); הוצאות הדוח → שנתיים קודם;
        הוצאות השנה הקודמת ודיבידנד 2025 לא בדוח – נשארים ריקים.
    יתרה ליום התחילה (1.1.2025) = עודפים לתום 2024, מאיזו עמודה שהיא נמצאת.
    """
    by_year = {k: {int(y): v for y, v in d.items()} for k, d in by_year.items()}
    f: dict[str, Any] = {}
    src: dict[str, str] = {}
    ty = tax_year or (report_year + 1)
    gap = ty - report_year
    ret, exp, div = by_year.get("retained", {}), by_year.get("expenses", {}), by_year.get("dividend", {})
    if report_year in ret:
        f["retained.balance_sheet_retained_earnings"] = ret[report_year]
        src["retained.balance_sheet_retained_earnings"] = raw_src.get("retained", "") + (f" (דוח {report_year} – ישן בשנה: אומדן, תרחיש ב׳)" if gap >= 2 else "")
    if 2024 in ret:
        f["distributions.retained_at_start_day"] = ret[2024]
        src["distributions.retained_at_start_day"] = raw_src.get("retained", "") + " (עודפים לתום 2024 = יתרה ליום התחילה 1.1.2025)"
    for y, v in exp.items():
        if y == ty - 1:
            f["shields.expenses_prev_year"] = v
            src["shields.expenses_prev_year"] = raw_src.get(f"expenses_{y}", "")
        elif y == ty - 2:
            f["shields.expenses_prev2_year"] = v
            src["shields.expenses_prev2_year"] = f"עמודת {y}: " + raw_src.get(f"expenses_{y}", "")
    if 2025 in div:
        f["distributions.dividend_in_determining_period"] = div[2025]
        src["distributions.dividend_in_determining_period"] = raw_src.get("dividend", "") + " – לוודא שחולק 1.1–30.11.2025 והמס שולם עד 31.12.2025"
    for key, path in (("capital", "shields.share_capital_and_premium"), ("cash", "shields.special_loans_deposits_cash")):
        if report_year in by_year.get(key, {}):
            f[path] = by_year[key][report_year]
            src[path] = raw_src.get(key, "")
    if gap >= 2:
        notes.append(f"הדוח הוא ל-{report_year} ושנת המס {ty} – תרחיש ב׳: העודפים הם אומדן עד שיש דוח {report_year + 1}; "
                     f"הוצאות {report_year + 1} ודיבידנד 2025 אינם בדוח – להזין ידנית")
    elif gap <= 0:
        notes.append(f"הדוח ל-{report_year} אינו מוקדם לשנת המס {ty} – לבדוק את שנת המס")
    return f, src

