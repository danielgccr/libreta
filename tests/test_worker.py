import pytest

from libreta.worker import Worker


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
        assert "<svg" in items[0][1]
        assert run(w, "len(plt.get_fignums())") == [("text/plain", "0")]  # all closed
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
