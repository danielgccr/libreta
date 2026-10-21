import ast

from libreta.cli import main
from libreta.purl import purl


def test_script_with_imports_on_top(tmp_path):
    (tmp_path / "util.py").write_text("")
    text = (
        "---\ntitle: Informe\nparams:\n  mes: 9\n---\n# Datos\n\nCargamos.\n\n"
        "```python\nimport pandas as pd\nimport os\nfrom util import limpiar\n"
        "df = pd.DataFrame({'a': [params['mes']]})\n```\n\n"
        "```python\nfrom __future__ import annotations\nimport numpy as np\nimport pandas as pd\n"
        "try:\n    import polars\nexcept ImportError:\n    polars = None\nnp.mean(df.a)\n```\n"
    )
    script, problems = purl(text, tmp_path)
    assert problems == []
    assert script == (
        "# Informe\n\n"
        "from __future__ import annotations\n\n"
        "import os\n\n"
        "import numpy as np\nimport pandas as pd\n\n"
        "from util import limpiar\n\n"
        "params = {'mes': 9}\n\n"
        "# # Datos\n#\n# Cargamos.\n\n"
        "df = pd.DataFrame({'a': [params['mes']]})\n\n"
        "try:\n    import polars\nexcept ImportError:\n    polars = None\nnp.mean(df.a)\n"
    )
    ast.parse(script)


def test_names_must_be_defined_above(tmp_path):
    text = (
        "```python\nimport numpy as np\nnp.mean(a)\n```\n\n"  # a: only in the next block
        "```python\na = [1, 2]\nb = b + 1\nc += 1\ndisplay(a)\n```\n"
    )
    script, problems = purl(text, tmp_path)
    assert script == ""
    assert problems == [
        "línea 3: «a» no está definido en ese punto",
        "línea 8: «b» no está definido en ese punto",
        "línea 9: «c» no está definido en ese punto",
        "línea 10: «display» solo existe dentro de libreta",
    ]


def test_scopes_that_are_fine(tmp_path):
    code = """def f(x, k=1):
    return x + later
later = 1
squares = [i * i for i in range(3)]
class A:
    n = 2
    m = n * 2
for j in range(2):
    print(j)
with open(__file__) as fh:
    fh.read()
try:
    1 / 0
except ZeroDivisionError as e:
    print(e)
match squares:
    case [first, *rest]:
        print(first, rest)
if (total := sum(squares)) > 0:
    print(total)
f(1)
"""
    assert purl(f"```python\n{code}```\n", tmp_path)[1] == []
    # Comprehension and class names stay inside them.
    _, problems = purl(
        "```python\n[i for i in range(3)]\nclass A:\n    n = 1\nprint(i, n)\n```\n", tmp_path
    )
    assert problems == [
        "línea 5: «i» no está definido en ese punto",
        "línea 5: «n» no está definido en ese punto",
    ]


def test_cli(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("Texto\n\n```python\nx = 1\n```\n")
    assert main(["purl", str(path)]) == 0
    assert capsys.readouterr().out == "# Texto\n\nx = 1\n"
    path.write_text("```python\nx = (\n```\n")
    assert main(["purl", str(path)]) == 1
    assert "línea 2: error de sintaxis" in capsys.readouterr().err
