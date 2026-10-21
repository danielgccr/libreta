"""How a block's results become output items: last expression, _repr_*_ protocol, streams."""

import ast
import base64
import io
from collections.abc import Callable

from libreta.i18n import number, tr

REPRS = [
    ("_repr_html_", "text/html"),
    ("_repr_svg_", "image/svg+xml"),
    ("_repr_png_", "image/png"),
    ("_repr_jpeg_", "image/jpeg"),
    ("_repr_latex_", "text/latex"),  # text in the editor, a formula in the export
    ("_repr_markdown_", "text/markdown"),  # shown as text in v1
]


def represent(value: object) -> tuple[str, str | bytes]:
    """The richest (mime, content) the value offers, falling back to repr(). A
    _repr_mimebundle_ (Altair, plotly, sympy...) answers first for each type."""
    bundle = _call(value, "_repr_mimebundle_")
    bundle = bundle if isinstance(bundle, dict) else {}
    for name, mime in REPRS:
        data = bundle.get(mime)
        if data is None:
            data = _call(value, name)
        if isinstance(data, str) and mime in ("image/png", "image/jpeg"):
            data = base64.b64decode(data)  # binary data travels in base64 in bundles
        if isinstance(data, str | bytes):
            return mime, data
    plain = bundle.get("text/plain")
    return "text/plain", plain if isinstance(plain, str) else repr(value)


def _call(value: object, name: str) -> object:
    # Looked up on the type: instance __getattr__ magic and classes themselves
    # (pd.DataFrame, not a frame) must not answer.
    method = getattr(type(value), name, None)
    if not callable(method):
        return None
    try:
        data = method(value)
    except Exception:
        return None
    return data[0] if isinstance(data, tuple) else data  # (data, metadata)


def split_last_expression(source: str, filename: str) -> tuple[ast.Module, ast.Expression | None]:
    """Split off a trailing expression to eval and show, unless its line ends in ';'."""
    tree = ast.parse(source, filename)
    last = tree.body[-1] if tree.body else None
    if isinstance(last, ast.Expr) and not _silenced(source, last):
        tree.body.pop()
        return tree, ast.Expression(last.value)
    return tree, None


def _silenced(source: str, node: ast.expr | ast.stmt) -> bool:
    line = source.splitlines()[node.end_lineno - 1]
    rest = line.encode()[node.end_col_offset :].decode()  # ast offsets are UTF-8 bytes
    return rest.lstrip().startswith(";")


def collapse(text: str) -> str:
    """A carriage return rewrites its line, as in a terminal (progress bars): keep what
    follows the last one. A trailing \r waits for the text that replaces the line.
    Twin of collapse() in static/js/blocks.js."""
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line[line.rfind("\r", 0, len(line) - 1) + 1 :] for line in lines)


MAX_LINES = 2000  # what a stream keeps: its last lines


def keep_tail(text: str) -> str:
    """A stream past twice MAX_LINES keeps its last MAX_LINES, after a line that counts the
    rest: a loop printing 100 000 lines stays light. Twin of appendStream() in blocks.js."""
    lines = text.split("\n")
    if len(lines) <= 2 * MAX_LINES:
        return text
    omitted = tr("… {count} líneas anteriores omitidas\n", count=number(len(lines) - MAX_LINES))
    return omitted + "\n".join(lines[-MAX_LINES:])


class Stream(io.TextIOBase):
    """sys.stdout/sys.stderr replacement: every write becomes one output item."""

    encoding = "utf-8"

    def __init__(self, kind: str, emit: Callable[[str, str], None]):
        self.kind = kind
        self._emit = emit

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if s:
            self._emit(self.kind, s)  # ponytail: one message per write; batch if it gets slow
        return len(s)
