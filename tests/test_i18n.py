import ast
import re
from datetime import datetime
from pathlib import Path

from test_app import get

from libreta import app, i18n
from libreta.i18n import EN, number, tr

SRC = Path(__file__).parent.parent / "src" / "libreta"


def test_every_text_has_its_translation():
    """Each tr("...") in Python and JS, and each {{...}} in the pages, is in the catalog;
    and the catalog holds nothing else."""
    found = set()
    for file in [*SRC.glob("*.py"), *SRC.glob("static/js/*.js")]:
        text = file.read_text(encoding="utf-8")
        literals = re.findall(r'\btr\(\s*("(?:[^"\\]|\\.)*")', text)
        found.update(ast.literal_eval(s) for s in literals)
    for file in SRC.glob("templates/*.html"):
        found.update(re.findall(r"\{\{(.+?)\}\}", file.read_text(encoding="utf-8")))
    found.update(["{count} documento", "{count} documentos"])  # chosen by count
    assert found - EN.keys() == set()
    assert EN.keys() - found == set()


def test_english(monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "MESSAGES", EN)
    monkeypatch.setattr(i18n, "LANG", "en")
    monkeypatch.setattr(app, "LANG", "en")
    monkeypatch.setattr(app, "MESSAGES", EN)
    assert tr("línea {line}: el bloque falla", line=3) == "line 3: the block fails"
    assert tr("un texto sin traducir") == "un texto sin traducir"
    assert number(12345) == "12,345"
    now = datetime(2026, 10, 22, 21, 0)
    assert app.when(datetime(2026, 10, 22, 9, 5).timestamp(), now) == "today, 9:05"
    assert app.when(datetime(2025, 3, 3).timestamp(), now) == "3 Mar 2025"
    doc_app = app.create_app(tmp_path, "secret")
    _, _, body = get(cookie="secret", path="/edit/doc.md", app=doc_app)
    assert b'<html lang="en">' in body and b'placeholder="Untitled"' in body
    assert b'"Saved": ' not in body and b'"Guardado": "Saved"' in body  # for editor.js
    _, _, body = get(cookie="secret", app=doc_app)
    assert b"0 documents" in body and b"<button>Create</button>" in body


def test_spanish():
    assert tr("línea {line}: el bloque falla", line=3) == "línea 3: el bloque falla"
    assert number(12345) == "12.345"
