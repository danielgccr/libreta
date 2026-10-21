"""One child process per document, holding the namespace where blocks are exec'd.

The child runs the Python of the document's project (see `environment`), not necessarily
libreta's: a subprocess of that interpreter, talking to the parent over a socket with
multiprocessing's Connection protocol. A block's output is streamed as ``(mime, content)``
items, where mime is a real MIME type for displayed values or one of ``stdout``,
``stderr`` and ``error`` (a formatted traceback).
"""

import builtins
import functools
import importlib.util
import linecache
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import traceback
from collections.abc import Iterator
from multiprocessing.connection import Connection
from pathlib import Path

from libreta import display

# The child's first lines. Whatever the project's Python, libreta's own modules (and jedi,
# for completion) come from libreta's installation, and nothing else of it leaks in.
BOOT = """
import importlib.machinery, sys
from multiprocessing.connection import Connection
own = dict(zip(("libreta", "jedi", "parso"), sys.argv[3:]))
class Own:
    @staticmethod
    def find_spec(name, path=None, target=None):
        if path is None and name in own:
            return importlib.machinery.PathFinder.find_spec(name, [own[name]])
sys.meta_path.insert(0, Own)
from libreta.worker import _main
_main(Connection(int(sys.argv[1])), sys.argv[2])
"""


def _home(package: str) -> str:
    """The folder a package is imported from, without importing it."""
    return str(Path(importlib.util.find_spec(package).origin).parent.parent)


def environment(directory: Path) -> tuple[str, dict[str, str] | None]:
    """The Python of the document's project, with its environment variables: the nearest
    .venv from the document's folder up (PEP 704), else the activated environment, else
    libreta's own Python. Looked up each time: a .venv made meanwhile counts."""
    directory = Path(os.path.abspath(directory))
    candidates = [d / ".venv" for d in (directory, *directory.parents)]
    if active := os.environ.get("VIRTUAL_ENV"):
        candidates.append(Path(active))
    for venv in candidates:
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if (venv / "pyvenv.cfg").is_file() and python.is_file() and _supported(str(python)):
            path = f"{python.parent}{os.pathsep}{os.environ.get('PATH', '')}"
            env = os.environ | {"VIRTUAL_ENV": str(venv), "PATH": path}  # as if activated
            env.pop("PYTHONHOME", None)
            return str(python), env
    return sys.executable, None


@functools.cache
def _supported(python: str) -> bool:
    check = "import sys; sys.exit(sys.version_info < (3, 12))"
    if subprocess.run([python, "-c", check]).returncode == 0:
        return True
    print(f"libreta: {python} es anterior a Python 3.12; se usa el de libreta", file=sys.stderr)
    return False


class Worker:
    def __init__(self, path: Path):
        python, env = environment(Path(path).parent)
        parent, child = socket.socketpair()
        with child:
            own = [_home(package) for package in ("libreta", "jedi", "parso")]
            self.process = subprocess.Popen(
                # -P: no folder of the server in sys.path; _main puts the document's there.
                [python, "-P", "-c", BOOT, str(child.fileno()), str(path), *own],
                pass_fds=[child.fileno()],
                env=env,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # Ctrl+C in the server's terminal is not for it
            )
        self.conn = Connection(parent.detach())
        self.unfinished = False  # a run whose output was not read to the end

    def alive(self) -> bool:
        return self.process.poll() is None

    def run(self, code: str, lineno: int, source: str) -> Iterator[tuple[str, str | bytes]]:
        """Execute `code`, whose first line is line `lineno` of the document `source`."""
        yield from self._request(("run", code, lineno, source))

    def inline(self, expressions: list[str], source: str) -> dict[str, dict]:
        """Evaluate inline `py` expressions: ``{expr: {"text": str(value)} | {"error": ...}}``.
        What they print is dropped; a dead worker gives no values."""
        values = {}
        for kind, content in self._request(("inline", expressions, source)):
            if kind == "values":
                values = content
        return values

    def assist(self, kind: str, code: str, line: int, column: int) -> list[dict]:
        """jedi on the live namespace (DESIGN §6.6). kind "complete": ``[{name, complete,
        type}]``, where `complete` is what to insert at the cursor; kind "signature":
        ``[{name, params, index}]``, `index` being the parameter under the cursor."""
        result = []
        for mime, content in self._request((kind, code, line, column, "")):
            if mime == "assist":
                result = content
        return result

    def _request(self, message: tuple) -> Iterator[tuple[str, str | bytes]]:
        for _ in self._messages():  # leftovers of an abandoned run (client went away)
            pass
        self.conn.send(message)
        self.unfinished = True
        yield from self._messages()

    def _messages(self) -> Iterator[tuple[str, str | bytes]]:
        while self.unfinished:
            try:
                message = self.conn.recv()
            except (EOFError, ConnectionResetError):  # the child died (reset: at startup)
                self.unfinished = False
                yield "error", "El proceso del worker ha terminado.\n"
                return
            if message[0] == "done":
                self.unfinished = False
                return
            yield message[1], message[2]

    def interrupt(self) -> None:
        os.kill(self.process.pid, signal.SIGINT)

    def close(self) -> None:
        self.conn.close()  # the child sees EOF and exits
        try:
            self.process.wait(1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


# Child side. SIGINT raises KeyboardInterrupt only while a block runs, and never while the
# main thread is halfway through writing a message (that would corrupt the pipe).

_conn = None
_lock = threading.Lock()
_running = False
_sending = False
_pending = False


def emit(mime: str, content: str | bytes) -> None:
    """Send one output item of the running block (used by the streams and libreta._mpl)."""
    _send(("output", mime, content))


def show(*objects: object) -> None:
    """Jupyter's display(), a builtin in the worker: each object shown where it is called,
    as a block's last expression is."""
    for obj in objects:
        if obj is not None:
            emit(*display.represent(obj))


def _send(message: tuple) -> None:
    global _sending, _pending
    main = threading.current_thread() is threading.main_thread()
    with _lock:
        _sending = main
        try:
            _conn.send(message)
        finally:
            _sending = False
    if main and _pending and _running:
        _pending = False
        raise KeyboardInterrupt


def _on_sigint(signum, frame):
    global _pending
    if _sending:
        _pending = True
    elif _running:
        raise KeyboardInterrupt


def _main(conn, filename: str) -> None:
    global _conn, _running
    _conn = conn
    signal.signal(signal.SIGINT, _on_sigint)
    os.environ["MPLBACKEND"] = "module://libreta._mpl"
    # Like knitr: relative paths and local imports resolve next to the document.
    directory = os.path.dirname(os.path.abspath(filename))
    os.chdir(directory)
    sys.path.insert(0, directory)
    # ponytail: Python-level capture only; output written straight to fd 1/2 (C extensions,
    # subprocesses) goes to the parent's terminal. Redirect the fds if that matters.
    sys.stdout = display.Stream("stdout", emit)
    sys.stderr = display.Stream("stderr", emit)
    builtins.display = show  # a builtin: a user's own `display` shadows it
    namespace = {"__name__": "__main__"}
    while True:
        try:
            kind, *args, source = conn.recv()
        except EOFError:
            return
        # Tracebacks quote the document being edited, not the file on disk.
        if source:  # completion requests carry none
            linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
        try:
            if kind == "run":
                _execute(namespace, *args, filename)
            elif kind == "inline":
                values = {e: _evaluate(namespace, e, filename) for e in args[0]}
                _send(("output", "values", values))
            else:
                _send(("output", "assist", _assist(kind, namespace, *args)))
        except KeyboardInterrupt:  # landed between the user's code and our bookkeeping
            _running = False
            emit("error", "KeyboardInterrupt\n")
        _send(("done",))


def _execute(namespace: dict, code: str, lineno: int, filename: str) -> None:
    global _running, _pending
    # Padding puts every line (and SyntaxError) at its line in the .md.
    source = "\n" * (lineno - 1) + code.replace("\r\n", "\n").replace("\r", "\n")
    try:
        body, last = display.split_last_expression(source, filename)
    except SyntaxError as e:
        emit("error", "".join(traceback.format_exception_only(e)))
        return
    error = None
    _pending = False
    _running = True
    try:
        try:
            exec(compile(body, filename, "exec"), namespace)
            if last is not None:
                value = eval(compile(last, filename, "eval"), namespace)
                if value is not None:
                    emit(*display.represent(value))
        finally:
            if mpl := sys.modules.get("libreta._mpl"):
                mpl.show()  # figures left open without plt.show()
    except BaseException as e:  # SystemExit and KeyboardInterrupt included
        error = e
    _running = False
    if error is not None:
        emit("error", _format(error, filename))


def _evaluate(namespace: dict, expression: str, filename: str) -> dict:
    """An inline `py` value as prose shows it: str(), not repr()."""
    global _running, _pending
    _pending = False
    _running = True
    try:
        result = {"text": str(eval(compile(expression, filename, "eval"), namespace))}
    except BaseException as e:
        result = {"error": traceback.format_exception_only(e)[-1].strip()}
    _running = False
    return result


def _assist(kind: str, namespace: dict, code: str, line: int, column: int) -> list[dict]:
    import jedi  # only now: a worker that never completes never loads it

    try:
        script = jedi.Interpreter(code, namespaces=[namespace])
        if kind == "signature":
            return [
                {"name": s.name, "params": [p.to_string() for p in s.params], "index": s.index}
                for s in script.get_signatures(line, column)
            ]
        before = code.splitlines()[line - 1][:column] if code else ""
        word = re.search(r"\w*\Z", before)[0]
        # What jedi takes as typed must be what is typed, and cover the whole word: it also
        # matches other cases (os.pa -> PathLike, whose `complete` would give "pathLike")
        # and, in a comment, offers every name as if nothing had been typed.
        return [
            {"name": c.name, "complete": c.complete, "type": c.type}
            for c in script.complete(line, column)
            if before.endswith(typed := c.name[: len(c.name) - len(c.complete)])
            and typed.endswith(word)
        ]
    except Exception:  # jedi on half-written code: no help rather than an error
        return []


def _format(error: BaseException, filename: str) -> str:
    """Traceback from the first frame of the user's code, without our own frames around it
    (the exec call before it, the SIGINT handler after a KeyboardInterrupt)."""
    tb = error.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename != filename:
        tb = tb.tb_next
    report = traceback.TracebackException(type(error), error, tb)
    while report.stack and report.stack[-1].filename == __file__:
        report.stack.pop()
    return "".join(report.format())
