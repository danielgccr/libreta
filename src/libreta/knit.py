"""The knitted Markdown: the source with the cached results woven in (DESIGN §10).

Inline `py` values replace their spans. Each Python block becomes a ``::: {.chunk}`` div
(the grey block of the editor) holding its code and outputs: text in ``{.output}`` fences,
HTML as a raw ``{=html}`` block, Markdown as is, figures as files linked from
``<name>_files/``. The result is input for Pandoc's commonmark_x, not for GitHub.
"""

import base64
import mimetypes
import re
from pathlib import Path

from libreta.cache import GENESIS, Cache, chain
from libreta.document import expressions, parse, substitute

TEXT = {
    "stdout": "{.output}",
    "stderr": "{.output .stderr}",
    "error": "{.output .error}",
    "text/plain": "{.output}",
}


def complete(path: Path) -> bool:
    """Whether the cache holds every output and inline value of the document."""
    parsed = parse(path.read_text(encoding="utf-8"))
    keys = [GENESIS, *chain(b.code for b in parsed if b.kind == "python")]
    cache = Cache(path)
    blocks = all(cache.load(k) is not None for k in keys[1:])
    values = all(
        cache.load_values(k) is not None
        for k, e in zip(keys, expressions(parsed), strict=True)
        if e
    )
    return blocks and values


def knit(path: Path) -> tuple[str, list[str]]:
    """The knitted Markdown of the document at `path`, writing its figures to
    ``<name>_files/``; and the problems found (missing outputs, failed inline values)."""
    source = path.read_text(encoding="utf-8")
    parsed = parse(source)
    keys = [GENESIS, *chain(b.code for b in parsed if b.kind == "python")]
    cache = Cache(path)
    files = path.with_name(f"{path.stem}_files")
    for old in files.glob("figura-*"):
        old.unlink()
    problems: list[str] = []
    figures = 0
    point = 0  # the point of the document: keys[point] is the state here
    out = []

    def value(expression: str) -> str | None:
        result = (cache.load_values(keys[point]) or {}).get(expression, {})
        if "text" not in result:
            problems.append(f"`py {expression}`: {result.get('error', 'sin valor en la caché')}")
        return result.get("text")

    for block in parsed:
        if block.kind == "markdown":
            out.append(substitute(block.text, value))
            continue
        point += 1
        code = block.text if block.text.endswith("\n") else block.text + "\n"
        if not block.close:  # left open at the end of the file
            code += re.match(r" *(`{3,}|~{3,})", code)[1] + "\n"
        parts = [code]
        items = cache.load(keys[point])
        if items is None:
            problems.append(f"línea {block.line}: el bloque no tiene salida en la caché")
            items = []
        if any(item["mime"] == "error" for item in items):
            problems.append(f"línea {block.line}: el bloque falla")
        for mime, content in _merge(items):
            if mime in TEXT:
                parts.append(_fenced(content, TEXT[mime]))
            elif mime == "text/html":
                parts.append(_fenced(content, "{=html}"))
            elif mime == "text/markdown":
                parts.append(content.rstrip("\n") + "\n")
            elif mime.startswith("image/"):
                figures += 1
                files.mkdir(exist_ok=True)
                name = f"figura-{figures}{mimetypes.guess_extension(mime) or ''}"
                (files / name).write_bytes(content)
                parts.append(f"![]({files.name}/{name}){_width(mime, content)}\n")
        out.append("\n::: {.chunk}\n" + "\n".join(parts) + ":::\n\n")
    return "".join(out), problems


def _merge(items: list[dict]) -> list[tuple[str, str | bytes]]:
    """(mime, content) with consecutive writes to the same stream joined, as the editor
    shows them; images decoded."""
    merged: list[tuple[str, str | bytes]] = []
    for item in items:
        mime = item["mime"]
        content = base64.b64decode(item["base64"]) if "base64" in item else item["content"]
        if mime in ("stdout", "stderr") and merged and merged[-1][0] == mime:
            merged[-1] = (mime, merged[-1][1] + content)
        else:
            merged.append((mime, content))
    return merged


def _width(mime: str, svg: bytes) -> str:
    """As in the editor (FIGURE_WIDTH in blocks.js): an SVG at the scale where a default
    matplotlib figure, 6.8in, fills the block."""
    m = re.search(rb'<svg[^>]*\swidth="([\d.]+)pt"', svg) if mime == "image/svg+xml" else None
    return f"{{width={min(100, float(m[1]) / (6.8 * 72) * 100):.4g}%}}" if m else ""


def _fenced(text: str, info: str) -> str:
    """A fence longer than any run of backticks in `text`."""
    ticks = "`" * max([3, *(len(run) + 1 for run in re.findall(r"`+", text))])
    return f"{ticks} {info}\n{text.rstrip(chr(10))}\n{ticks}\n"
