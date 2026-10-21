import os
import shutil

import pytest

from libreta.cli import main, run
from libreta.knit import complete, knit

SVG = '<svg width="244.8pt" height="100pt"></svg>'  # half the default figure width

DOC = f"""# Doc

Antes `py 1 + 1`.

```python
class Fig:
    def _repr_svg_(self):
        return {SVG!r}
class Md:
    def _repr_markdown_(self):
        return "**negrita**"
print("a")
print("```")
Fig()
```

Vale `py "**negrita**"` y `py nada`.

```python
Md()
```
"""


def test_knit(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text(DOC)
    assert not complete(path)
    assert run(path, keep_going=True) == 1  # `py nada` fails; the rest runs anyway
    assert complete(path)
    markdown, problems = knit(path)
    assert markdown == (
        "# Doc\n\nAntes 2.\n\n"
        "\n::: {.chunk}\n" + DOC.split("Antes `py 1 + 1`.\n\n")[1].split("\n\nVale")[0] + "\n\n"
        "```` {.output}\na\n```\n````\n\n"
        "![](doc_files/figura-1.svg){width=50%}\n"
        ":::\n\n"
        "\nVale **negrita** y `py nada`.\n\n"
        "\n::: {.chunk}\n```python\nMd()\n```\n\n**negrita**\n:::\n\n"
    )
    assert (tmp_path / "doc_files" / "figura-1.svg").read_text() == SVG
    assert problems == ["`py nada`: NameError: name 'nada' is not defined"]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="needs Pandoc")
def test_export_html(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("# Hola\n\n```python\nprint('x')\n1 / 0\n```\n\nY $x^2$.\n")
    assert main(["export", str(path)]) == 1  # exported, with the error in it
    html = (tmp_path / "doc.html").read_text()
    assert 'class="chunk"' in html and "ZeroDivisionError" in html and "<math" in html
    assert "--code-bg" in html  # tokens.css and export.css embedded
    assert not (tmp_path / "doc.knit.md").exists()  # converted: the intermediate goes
    assert "línea 3: el bloque falla" in capsys.readouterr().err
    (tmp_path / "doc_files").mkdir()
    (tmp_path / "doc_files" / "mio.txt").write_text("")  # not ours: kept, and its folder
    path.write_text("```python\nimport matplotlib.pyplot as plt\nplt.plot([1]);\n```\n")
    assert main(["export", str(path)]) == 0
    assert [p.name for p in (tmp_path / "doc_files").iterdir()] == ["mio.txt"]
    assert main(["export", str(path), "--keep-md"]) == 0
    assert (tmp_path / "doc.knit.md").exists() and (
        tmp_path / "doc_files" / "figura-1.svg"
    ).exists()


def test_changed_data_makes_the_cache_incomplete(tmp_path):
    path = tmp_path / "doc.md"
    data = tmp_path / "datos.txt"
    data.write_text("1")
    path.write_text("```python\nopen('datos.txt').read()\n```\n")
    assert run(path) == 0 and complete(path)
    os.utime(data, ns=(0, 0))
    assert not complete(path)  # export runs the document again
