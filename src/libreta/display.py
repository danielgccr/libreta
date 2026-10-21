"""How a block's results become output items: last expression, _repr_*_ protocol, streams."""

import ast
import io
from collections.abc import Callable

REPRS = [
    ("_repr_html_", "text/html"),
    ("_repr_svg_", "image/svg+xml"),
    ("_repr_png_", "image/png"),
    ("_repr_markdown_", "text/markdown"),  # shown as text in v1
]


def represent(value: object) -> tuple[str, str | bytes]:
    """The richest (mime, content) the value offers, falling back to repr()."""
    for name, mime in REPRS:
        # Looked up on the type: instance __getattr__ magic and classes themselves
        # (pd.DataFrame, not a frame) must not answer.
        method = getattr(type(value), name, None)
        if not callable(method):
            continue
        try:
            data = method(value)
        except Exception:
            continue
        if isinstance(data, tuple):  # (data, metadata)
            data = data[0]
        if isinstance(data, str | bytes):
            return mime, data
    return "text/plain", repr(value)


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
