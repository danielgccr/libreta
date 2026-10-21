from libreta.cache import Cache, chain
from libreta.cli import main

DOC = """# Prueba

```python
def f(x):
    return 1 / x
print("antes")
```

```python
f(0)
```

```python
print("no llega")
```
"""


def test_run_reports_error_with_document_line(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text(DOC)
    assert main(["run", str(path)]) == 1
    out, err = capsys.readouterr()
    assert out == "antes\n"
    assert f'File "{path}", line 10' in err and f'File "{path}", line 5, in f' in err


def test_run_ok_and_cached(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("Texto\n\n```python\nx = 2\nx * 21\n```\n")
    assert main(["run", str(path)]) == 0
    assert capsys.readouterr().out == "42\n"
    [h] = chain(["x = 2\nx * 21\n"])
    assert Cache(path).load(h) == [{"mime": "text/plain", "content": "42"}]
    path.write_text("```python\n1\n```\n")
    assert main(["run", str(path)]) == 0
    assert Cache(path).load(h) is None  # pruned: no longer in the document


def test_run_missing_file(tmp_path):
    assert main(["run", str(tmp_path / "nope.md")]) == 2


def test_run_inline_values(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("```python\nx = 2\n```\n\nSon `py x * 21` y `py y`.\n")
    assert main(["run", str(path)]) == 1
    assert "`py y`: NameError: name 'y' is not defined" in capsys.readouterr().err
    [h] = chain(["x = 2\n"])
    assert Cache(path).load_values(h)["x * 21"] == {"text": "42"}


def test_export_missing_css(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("Hola\n")
    assert main(["export", str(path), "--css", str(tmp_path / "mio.css")]) == 2
    assert "no existe" in capsys.readouterr().err
    assert not (tmp_path / "doc.knit.md").exists()  # checked before doing anything


def test_run_with_params(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("---\nparams:\n  mes: 9\n---\n\n```python\nprint(params['mes'])\n```\n")
    assert main(["run", str(path)]) == 0
    assert main(["run", str(path), "-p", "mes=2026-10"]) == 0
    assert capsys.readouterr().out == "9\n2026-10\n"
    [h] = chain(["print(params['mes'])\n"], {"mes": "2026-10"})
    assert Cache(path).load(h) == [{"mime": "stdout", "content": "2026-10\n"}]
    assert main(["run", str(path), "-p", "anio=2026"]) == 2
    assert "no tiene ese parámetro (tiene: mes)" in capsys.readouterr().err
