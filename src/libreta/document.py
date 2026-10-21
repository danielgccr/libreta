"""Split a Markdown document into prose blocks and executable Python blocks.

The parser is line based and only knows the bits of CommonMark it needs: fenced code
blocks (to find top-level ```python fences and to skip the inside of any other fence),
ATX headings (each one opens a new Markdown block) and list items (a fence nested in a
list is prose). Every block keeps its exact source slice, so
``serialize(parse(text)) == text`` holds by construction.

Known simplifications: block quotes need no tracking (a fence line is never a lazy
continuation, so ``> ```python`` is always prose); thematic breaks such as ``* * *``
are read as list items; HTML blocks and setext headings are not recognised.
"""

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
FENCE_OPEN = re.compile(r"( {0,3})(`{3,}|~{3,})(.*)")
FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
HEADING = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
LIST_ITEM = re.compile(r"( {0,3})([-+*]|\d{1,9}[.)])( +|$)")
# A backslash escape (so \` opens nothing) or a code span, as in md-highlight.js.
CODE_SPAN = re.compile(r"\\[!-/:-@\[-`{-~]|(`+)([^`](?:.*?[^`])?)\1(?!`)")
INLINE_PY = re.compile(r"py\s")
FRONT_MATTER = re.compile(r"---[ \t]*\n(?:.*?\n)??(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)
PLAIN_YAML = re.compile(r"\w[\w .,;()¿?¡!'’-]*(?<! )")  # safe unquoted, as a string
YAML_LITERAL = re.compile(r"(?i)true|false|null|yes|no|on|off|~|[\d.eE+-]+")
TYPING_PY = re.compile(r"`py\s+([^`]*)\Z")  # an inline expression open up to the cursor


@dataclass(frozen=True)
class Block:
    kind: Literal["markdown", "python"]
    text: str  # exact source slice, fences included
    line: int  # 1-based line of the block's first line (the opening fence for python)
    code: str = ""  # python only: the fence content, without the fence indentation
    close: str = ""  # python only: the closing fence line ("" if the fence runs to EOF)


def serialize(blocks: list[Block]) -> str:
    return "".join(block.text for block in blocks)


def parse(text: str) -> list[Block]:
    lines = LINE.findall(text)
    blocks: list[Block] = []
    start = 0  # first line of the pending Markdown block
    list_indent: int | None = None  # content column of the open top-level list item
    prev_blank = False

    def flush(end: int) -> None:
        if end > start:
            blocks.append(Block("markdown", "".join(lines[start:end]), start + 1))

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        blank = not line.strip()
        expanded = line.expandtabs(4)
        if not blank and (list_indent is None or _indent(expanded) < list_indent):
            if item := LIST_ITEM.match(expanded):
                list_indent = _content_indent(item)
                prev_blank = False
                i += 1
                continue
            if list_indent is not None and (prev_blank or _fence_open(line) or HEADING.match(line)):
                list_indent = None
        prev_blank = blank
        if list_indent is not None:  # inside a list item, or a lazy continuation of one
            i += 1
            continue

        if fence := _fence_open(line):
            indent, marker, info = fence
            end, closed = _fence_end(lines, i, marker)
            if info.strip() == "python":
                flush(i)
                body = lines[i + 1 : end - 1 if closed else end]
                code = "".join(_dedent(body_line, indent) for body_line in body)
                close = lines[end - 1] if closed else ""
                blocks.append(Block("python", "".join(lines[i:end]), i + 1, code, close))
                start = end
            i = end
            continue

        if HEADING.match(line):
            flush(i)
            start = i
        i += 1

    flush(len(lines))
    return blocks


def _fence_open(line: str) -> tuple[int, str, str] | None:
    m = FENCE_OPEN.fullmatch(line)
    if not m or (m[2][0] == "`" and "`" in m[3]):
        return None
    return len(m[1]), m[2], m[3]


def _fence_end(lines: list[str], i: int, marker: str) -> tuple[int, bool]:
    """Index just past the closing fence, and whether there was one (else: end of file)."""
    for j in range(i + 1, len(lines)):
        m = FENCE_CLOSE.fullmatch(lines[j].rstrip("\r\n"))
        if m and m[1][0] == marker[0] and len(m[1]) >= len(marker):
            return j + 1, True
    return len(lines), False


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content_indent(item: re.Match[str]) -> int:
    pad = len(item[3])
    if not 1 <= pad <= 4 or item.end() == len(item.string):
        pad = 1
    return item.end(2) + pad


def _dedent(line: str, n: int) -> str:
    return line[min(n, _indent(line)) :]


def expressions(blocks: list[Block]) -> list[list[str]]:
    """The inline `py` expressions of the Markdown before the first Python block, then of
    the Markdown after each one: what each point of the document evaluates (DESIGN §4.7)."""
    sections: list[list[str]] = [[]]
    for block in blocks:
        if block.kind == "python":
            sections.append([])
        else:
            sections[-1] += _inline_python(block.text)
    return sections


def substitute(markdown: str, value: Callable[[str], str | None]) -> str:
    """`markdown` with each inline `py` span replaced by value(expression), or kept as it is
    where that gives None (DESIGN §10)."""
    lines = markdown.splitlines(keepends=True)
    for i, m in reversed(list(_py_spans(markdown))):  # right to left: offsets stay valid
        text = value(_expression(m))
        if text is not None:
            lines[i] = lines[i][: m.start()] + text + lines[i][m.end() :]
    return "".join(lines)


def _inline_python(markdown: str) -> list[str]:
    return [_expression(m) for _, m in _py_spans(markdown)]


def _py_spans(markdown: str) -> Iterator[tuple[int, re.Match[str]]]:
    """(line index, match) of each code span starting with `py `, line by line outside
    fences: the same ones md-highlight.js colours, so the editor finds a value for each."""
    fence = None
    for i, line in enumerate(markdown.splitlines()):
        if fence:
            m = FENCE_CLOSE.fullmatch(line)
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
                fence = None
        elif opening := _fence_open(line):
            fence = opening[1]
        else:
            for m in CODE_SPAN.finditer(line):
                if m[2] and INLINE_PY.match(m[2]):
                    yield i, m


def _expression(span: re.Match[str]) -> str:
    return span[2][2:].strip()


def code_at(text: str, line: int, column: int) -> tuple[str, int, int] | None:
    """What jedi sees at a cursor of the document (1-based line, 0-based column): the code of
    every Python block up to the cursor's, or before it plus the inline `py` expression
    typed so far. Returns (code, line, column) in that code, or None outside both."""
    blocks = [b for b in parse(text) if b.kind == "python" and b.line < line]
    codes = [b.code if b.code.endswith("\n") or not b.code else b.code + "\n" for b in blocks]
    if blocks and line - blocks[-1].line <= max(1, codes[-1].count("\n")):
        prefix = "".join(codes[:-1])
        return prefix + codes[-1], prefix.count("\n") + line - blocks[-1].line, column
    lines = text.split("\n")
    typing = TYPING_PY.search(lines[line - 1][:column]) if line <= len(lines) else None
    if typing is None:
        return None
    prefix = "".join(codes)
    return prefix + typing[1], prefix.count("\n") + 1, len(typing[1])


def split_front_matter(text: str) -> tuple[str, str]:
    """The YAML front matter, ``---`` lines included ("" if there is none), and the rest."""
    m = FRONT_MATTER.match(text)
    return (m[0], text[m.end() :]) if m else ("", text)


def front_value(front: str, key: str) -> str | None:
    """A top-level scalar of the front matter. Only one-line values: the editor reads the
    title and the date, it does not parse YAML."""
    m = re.search(rf"^{key}:[ \t]*(.*?)[ \t]*$", front, re.M)
    if m is None:
        return None
    value = m[1]
    if value.startswith('"'):
        try:
            return json.loads(value)  # close enough to YAML's double quotes
        except ValueError:
            return value.strip('"')
    if value.startswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def stamp(text: str, title: str, date: str) -> str:
    """The document as saving writes it: `title` in the front matter (removed if empty) and
    `date`, the day of the save. Only a title gives a document front matter it lacked."""
    front, body = split_front_matter(text)
    if not front:
        if not title:
            return text
        front = "---\n---\n"  # and no blank line after it: the editor's blocks are the body
    front = _set(front, "title", _yaml(title) if title else "", first=True)
    return _set(front, "date", date, first=False) + body  # ISO, unquoted: a YAML date


def _set(front: str, key: str, value: str, first: bool) -> str:
    """Replace the `key:` line with `value` (YAML already; "" removes it), or add it after the
    opening ``---`` (`first`) or before the closing one.
    ponytail: a multi-line value (``title: >``) would leave its tail behind."""
    line = f"{key}: {value}\n" if value else ""
    pattern = re.compile(rf"^{key}:.*\n", re.M)
    if pattern.search(front):
        return pattern.sub(lambda _: line, front, count=1)
    at = front.index("\n") + 1 if first else front.rstrip("\n").rfind("\n") + 1
    return front[:at] + line + front[at:]


def _yaml(value: str) -> str:
    plain = PLAIN_YAML.fullmatch(value) and not YAML_LITERAL.fullmatch(value)
    return value if plain else json.dumps(value, ensure_ascii=False)
