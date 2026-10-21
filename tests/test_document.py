import random
from pathlib import Path

import pytest

from libreta.document import expressions, parse, serialize

EJEMPLOS = sorted((Path(__file__).parent.parent / "ejemplos").glob("*.md"))


def kinds(text):
    return [b.kind for b in parse(text)]


def codes(text):
    return [b.code for b in parse(text) if b.kind == "python"]


@pytest.mark.parametrize("path", EJEMPLOS, ids=lambda p: p.name)
def test_roundtrip_examples(path):
    text = path.read_bytes().decode()
    assert serialize(parse(text)) == text


# Lines chosen to hit every branch of the parser; joined with mixed line endings.
PIECES = [
    "",
    " ",
    "  \t",
    "text",
    "trailing  ",
    "# h1",
    "## h2 ",
    "#nohead",
    "    # indented",
    "```python",
    "``` python",
    "~~~python",
    "````python",
    "```py",
    "```python`",
    "```bash",
    "```",
    "````",
    "~~~",
    "  ```python",
    "    ```python",
    "``` ",
    "x = 1",
    "  y = 2",
    "- item",
    "1. item",
    "* * *",
    "  - nested",
    "-",
    "> quote",
    "> ```python",
    "\tcode",
    "<div>",
    "ñandú ☃",
    "\x0c",
    " ",
]


def test_roundtrip_fuzz():
    rng = random.Random(0)
    for _ in range(3000):
        n = rng.randint(0, 25)
        text = "".join(rng.choice(PIECES) + rng.choice(["\n", "\r\n", "\r"]) for _ in range(n))
        if rng.random() < 0.5:
            text = text.rstrip("\r\n")
        blocks = parse(text)
        assert serialize(blocks) == text
        assert all(b.text for b in blocks)


def test_empty():
    assert parse("") == []


def test_simple_document():
    text = "Intro\n\n```python\nx = 1\nx\n```\n\nOutro\n"
    blocks = parse(text)
    assert [b.kind for b in blocks] == ["markdown", "python", "markdown"]
    assert blocks[0].text == "Intro\n\n"
    assert blocks[1].code == "x = 1\nx\n"
    assert blocks[2].text == "\nOutro\n"


@pytest.mark.parametrize(
    "text",
    [
        "```py\n1\n```\n",
        "```python3\n1\n```\n",
        "```Python\n1\n```\n",
        "```python {.x}\n1\n```\n",
        "```python`\n1\n```\n",  # backtick in info string: not a fence
        "    ```python\n    1\n    ```\n",  # indented code block
        "> ```python\n> 1\n> ```\n",
        "````markdown\n```python\n1\n```\n````\n",
        "- item\n\n  ```python\n  1\n  ```\n",
        "1. item\n   ```python\n   1\n   ```\n",
        "- a\n  - b\n\n    ```python\n    1\n    ```\n",
        "- item\nlazy\n  ```python\n  1\n  ```\n",
    ],
)
def test_not_executable(text):
    assert "python" not in kinds(text)


@pytest.mark.parametrize(
    "text, code",
    [
        ("``` python \n1\n```\n", "1\n"),  # info string is trimmed
        ("~~~python\n1\n~~~\n", "1\n"),
        ("````python\n```\nx\n````\n", "```\nx\n"),  # shorter fence is content
        ("```python\n1\n~~~\n```\n", "1\n~~~\n"),  # other fence char is content
        ("```python\n1\n```x\n2\n```\n", "1\n```x\n2\n"),  # closer takes no info
        ("```python\n1\n   ```  \nafter\n", "1\n"),
        ("```python\nunclosed\n", "unclosed\n"),
        ("```python", ""),
        ("  ```python\n  a = 1\n b\nc\n  ```\n", "a = 1\nb\nc\n"),
        ("```python\r\nx\r\n```\r\n", "x\r\n"),
        ("- item\n\n```python\n1\n```\n", "1\n"),  # blank + less indent ends the list
        ("- item\n```python\n1\n```\n", "1\n"),  # a fence interrupts the list item
        ("- item\n  more\n\n  text\n\n```python\n1\n```\n", "1\n"),
    ],
)
def test_executable(text, code):
    assert codes(text) == [code]


def test_headings_open_blocks():
    text = "# A\ntext\n#nohead\n## B\n\n```bash\n# no\n```\n```python\n# no\n```\n### C\n"
    blocks = parse(text)
    assert [b.text.split("\n")[0] for b in blocks] == ["# A", "## B", "```python", "### C"]


def test_consecutive_python_blocks():
    assert kinds("```python\n1\n```\n```python\n2\n```\n") == ["python", "python"]


def test_block_lines():
    text = "# A\r\n\r\n```python\r\n1\r\n```\r\n## B\n"
    assert [b.line for b in parse(text)] == [1, 3, 6]


def test_expressions_by_point_of_the_document():
    text = (
        "Antes `py 1 + 1` y `codigo`.\n\n"
        "```python\nx = 1\n```\n\n"
        "Vale `py x`, `pyx`, `` `py no` `` y \\`py no`.\n\n"
        "```bash\n`py no`\n```\n"
        "# Título `py  x * 2 `\n\n"
        "```python\ny = 2\n```\n"
    )
    assert expressions(parse(text)) == [["1 + 1"], ["x", "x * 2"], []]
    assert expressions(parse("")) == [[]]
