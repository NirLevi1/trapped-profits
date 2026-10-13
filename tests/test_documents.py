"""החלטות 19–20: שני דוחות, שלושה פורמטים."""
import json, tempfile
from pathlib import Path
from trapped_profits import compute
from trapped_profits.models import ClientInput
from trapped_profits.documents import build_accountant_doc, build_client_doc, render_html, render_docx, export

EXAMPLE = Path(__file__).parent.parent / "examples" / "example_client.json"
R = compute(ClientInput.from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8"))))


def test_accountant_doc_has_all_numbers():
    h = render_html(build_accountant_doc(R, {"status": "בשיחה", "note": "x"}))
    for needle in ("57,300", "429,900", "850,000", "35.4%", "מסלול 81", "מסלול 62א", "בשיחה"):
        assert needle in h


def test_client_letter_is_plain_language():
    h = render_html(build_client_doc(R, "משרד דוגמה", "אברהם"))
    assert "לכבוד" in h and "לסיכום" in h and "אברהם" in h
    for jargon in ("81ג", "62א(א1)", "מגן ב'", "רווחים נצברים חייבים"):
        assert jargon not in h


def test_export_html_docx_pdf():
    out = Path(tempfile.mkdtemp())
    assert export(R, "client", "html", out).suffix == ".html"
    d = export(R, "accountant", "docx", out)
    assert d.suffix == ".docx" and d.stat().st_size > 5000
    p = export(R, "client", "pdf", out)
    assert p.suffix in (".pdf", ".html")       # .html = אין ממיר במכונה (נפתח להדפסה)
