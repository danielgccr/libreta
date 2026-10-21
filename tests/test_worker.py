import venv

import pytest

from libreta.app import modules
from libreta.worker import Worker, environment


@pytest.fixture(scope="module")
def worker(tmp_path_factory):
    w = Worker(tmp_path_factory.mktemp("doc") / "doc.md")
    yield w
    w.close()


def run(worker, code, lineno=1, source=None):
    return list(worker.run(code, lineno, source if source is not None else code))


def test_value_streams_and_order(worker):
    code = "import sys\nprint('a')\nsys.stderr.write('b')\nprint('c', end='')\n40 + 2"
    assert run(worker, code) == [
        ("stdout", "a"),
        ("stdout", "\n"),
        ("stderr", "b"),
        ("stdout", "c"),
        ("text/plain", "42"),
    ]
    assert run(worker, "x = 1") == []
    assert run(worker, "None") == []
    assert run(worker, "x;") == []


def test_state_persists_and_rich_display(worker):
    run(worker, "class H:\n    def _repr_html_(self):\n        return '<b>h</b>'\nh = H()")
    assert run(worker, "h") == [("text/html", "<b>h</b>")]


def test_cwd_and_name(worker, tmp_path_factory):
    [(_, cwd)] = run(worker, "import os\nos.getcwd()")
    assert cwd.strip("'").endswith("doc0")
    assert run(worker, "__name__") == [("text/plain", "'__main__'")]


def test_traceback_points_at_document_lines(worker):
    source = "# Doc\n\n```python\ndef f():\n    return 1 / 0\n```\n\n```python\nf()\n```\n"
    run(worker, "def f():\n    return 1 / 0\n", 4, source)
    [(mime, tb)] = run(worker, "f()\n", 9, source)
    assert mime == "error"
    assert 'doc.md", line 9, in <module>\n    f()' in tb
    assert 'doc.md", line 5, in f\n    return 1 / 0' in tb
    assert "worker.py" not in tb and tb.endswith("ZeroDivisionError: division by zero\n")


def test_syntax_error_line(worker):
    [(mime, tb)] = run(worker, "x = 1\nx = (\n", 10, "\n" * 9 + "x = 1\nx = (\n")
    assert mime == "error" and "line 11" in tb and "SyntaxError" in tb


def test_system_exit_keeps_worker(worker):
    [(mime, tb)] = run(worker, "raise SystemExit(3)")
    assert mime == "error" and "SystemExit: 3" in tb
    assert run(worker, "1") == [("text/plain", "1")]


def test_interrupt(worker):
    items = []
    # Short sleeps: a SIGINT landing just before a long sleep() starts is only seen after it.
    code = "import time\nprint('ready')\nwhile True:\n    time.sleep(0.01)"
    for item in worker.run(code, 1, ""):
        items.append(item)
        if item == ("stdout", "ready"):
            worker.interrupt()
    assert items[-1][0] == "error" and items[-1][1].endswith("in <module>\nKeyboardInterrupt\n")
    assert "worker.py" not in items[-1][1]
    assert run(worker, "'still alive'") == [("text/plain", "'still alive'")]


def test_abandoned_run_is_drained(worker):
    items = worker.run("print('a')\nprint('b')\n'last'", 1, "")
    assert next(items) == ("stdout", "a")
    items.close()  # the browser went away mid-run
    assert run(worker, "2") == [("text/plain", "2")]


def test_interrupt_while_idle_is_ignored(worker):
    worker.interrupt()
    assert run(worker, "2") == [("text/plain", "2")]


def test_worker_death(tmp_path):
    w = Worker(tmp_path / "doc.md")
    try:
        [(mime, _)] = run(w, "import os\nos._exit(1)")
        assert mime == "error"
    finally:
        w.close()


def test_matplotlib_figures_in_order(tmp_path):
    pytest.importorskip("matplotlib")
    w = Worker(tmp_path / "doc.md")
    try:
        code = "import matplotlib.pyplot as plt\nplt.plot([1])\nplt.show()\n"
        code += "print('x')\nplt.plot([2]);"
        items = run(w, code)
        assert [mime for mime, _ in items] == ["image/svg+xml", "stdout", "stdout", "image/svg+xml"]
        assert 'width="489.6pt" height="302.4pt"' in items[0][1]  # the figsize, not trimmed
        assert run(w, "len(plt.get_fignums())") == [("text/plain", "0")]  # all closed
        [(mime, png)] = run(w, "plt.scatter(range(20_000), range(20_000));")  # SVG: 2 MB
        assert mime == "image/png" and png.startswith(b"\x89PNG")
        [(mime, png)] = run(w, "plt.rcParams['savefig.format'] = 'png'\nplt.plot([1]);")
        assert mime == "image/png" and png.startswith(b"\x89PNG")
    finally:
        w.close()


def test_inline_values(worker):
    run(worker, "z = 2.5\nclass Bad:\n    def __str__(self):\n        raise ValueError('no')")
    values = worker.inline(["z * 2", "'texto'", "print('x') or 1", "nada", "Bad()", "1 +"], "")
    assert values["z * 2"] == {"text": "5.0"}
    assert values["'texto'"] == {"text": "texto"}  # str(), not repr()
    assert values["print('x') or 1"] == {"text": "1"}  # what it prints is dropped
    assert values["nada"] == {"error": "NameError: name 'nada' is not defined"}
    assert values["Bad()"] == {"error": "ValueError: no"}
    assert values["1 +"]["error"].startswith("SyntaxError")
    assert run(worker, "z") == [("text/plain", "2.5")]


def test_assist(worker):
    run(worker, "d = {'alpha': 1}\nimport os")
    names = {c["name"]: c for c in worker.assist("complete", "d.", 1, 2)}
    assert names["keys"] == {"name": "keys", "complete": "keys", "type": "function"}
    [key] = worker.assist("complete", 'd["', 1, 3)  # live objects: dict keys
    assert key["complete"] == 'alpha"'
    pa = worker.assist("complete", "os.pa", 1, 5)
    assert "path" in {c["name"] for c in pa} and "PathLike" not in {c["name"] for c in pa}
    assert worker.assist("complete", "import json\njson.lo", 2, 7)[0]["name"] == "load"
    assert worker.assist("complete", "# hol", 1, 5) == []  # comments: nothing to offer
    assert [c["name"] for c in worker.assist("complete", "pri", 1, 3)] == ["print"]
    [sig] = worker.assist("signature", "divmod(1, ", 1, 10)[:1]
    assert sig["name"] == "divmod" and sig["index"] == 1 and len(sig["params"]) == 2
    assert worker.assist("complete", "x", 5, 0) == []  # jedi raises: no help, no error
    assert run(worker, "1") == [("text/plain", "1")]


def test_display_builtin(worker):
    code = "for i in range(2):\n    display(i, None)\nprint('fin')\ndisplay = 5\ndisplay"
    assert run(worker, code) == [
        ("text/plain", "0"),
        ("text/plain", "1"),
        ("stdout", "fin"),
        ("stdout", "\n"),
        ("text/plain", "5"),  # the user's own display shadows the builtin
    ]
    run(worker, "del display")


def test_project_environment(tmp_path):
    """A document inside a project with its own .venv runs in that Python (PEP 704), with
    libreta's modules and jedi lent to it and nothing else of libreta's environment."""
    venv.create(tmp_path / ".venv", with_pip=False)
    (tmp_path / "informes").mkdir()
    doc = tmp_path / "informes" / "doc.md"
    python, env = environment(doc.parent)
    assert python == str(tmp_path / ".venv" / "bin" / "python")
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    w = Worker(doc)
    try:
        [(_, prefix)] = run(w, "import sys\nsys.prefix")
        assert prefix == repr(str(tmp_path / ".venv"))
        [(mime, error)] = run(w, "import starlette")  # libreta's, not the project's
        assert mime == "error" and "ModuleNotFoundError" in error
        assert run(w, "display('visto')") == [("text/plain", "'visto'")]
        assert "dumps" in {c["name"] for c in w.assist("complete", "import json\njson.du", 2, 7)}
    finally:
        w.close()
    names = modules(doc.parent)
    assert "json" in names and "starlette" not in names


def test_top_level_await(worker):
    run(worker, "import asyncio\nasync def loop_of():\n    return asyncio.get_running_loop()")
    assert run(worker, "x = await asyncio.sleep(0, result=21)\nx * 2") == [("text/plain", "42")]
    run(worker, "first = await loop_of()")
    assert run(worker, "(await loop_of()) is first") == [("text/plain", "True")]  # one loop
    assert worker.inline(["await asyncio.sleep(0, result='sí')"], "") == {
        "await asyncio.sleep(0, result='sí')": {"text": "sí"}
    }
    assert run(worker, "asyncio.run(asyncio.sleep(0, result=1))") == [("text/plain", "1")]


def test_interrupt_await(worker):
    run(worker, "import asyncio\nawait asyncio.sleep(0)")  # a loop already made: it once hung
    items = []
    code = "import asyncio\nticks = 0\nprint('ready')\nwhile True:\n"
    code += "    ticks += 1\n    await asyncio.sleep(0.01)"
    for item in worker.run(code, 1, ""):
        items.append(item)
        if item == ("stdout", "ready"):
            worker.interrupt()
    assert items[-1][0] == "error" and items[-1][1].endswith("KeyboardInterrupt\n")
    [(_, before)] = run(worker, "ticks")
    run(worker, "await asyncio.sleep(0.05)")  # the loop runs again: the old task must not
    assert run(worker, "ticks") == [("text/plain", before)]


def test_reads_data_files_under_the_folder(tmp_path):
    (tmp_path / "datos.csv").write_text("a\n1\n")
    (tmp_path / "tabla.parquet").write_bytes(b"PAR1")
    (tmp_path / ".oculto").mkdir()
    (tmp_path / ".oculto" / "x.txt").write_text("x")
    w = Worker(tmp_path / "doc.md")
    try:
        assert w.reads == {}
        run(w, "texto = open('datos.csv').read()\nopen('.oculto/x.txt').read()")
        assert list(w.reads) == ["datos.csv"]  # hidden folders (.venv, .libreta) do not count
        # Opened from C (pyarrow, polars): only its name in the code gives it away.
        run(w, "ruta = 'tabla.parquet'\nno_existe = 'otra.parquet'")
        assert sorted(w.reads) == ["datos.csv", "tabla.parquet"]
        st = (tmp_path / "datos.csv").stat()
        assert w.reads["datos.csv"] == [st.st_mtime_ns, st.st_size]
        run(w, "open('salida.txt', 'w').write('hola')")  # written: as it is afterwards
        assert w.reads["salida.txt"][1] == 4
    finally:
        w.close()


def test_params(tmp_path):
    w = Worker(tmp_path / "doc.md", {"mes": "2026-09", "n": 3})
    try:
        assert run(w, "params['n'] * 2, params['mes']") == [("text/plain", "(6, '2026-09')")]
    finally:
        w.close()
    assert "NameError" in run(worker := Worker(tmp_path / "doc.md"), "params")[0][1]
    worker.close()
