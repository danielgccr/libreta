import ast

from libreta.display import represent, split_last_expression


class Html:
    def _repr_html_(self):
        return "<b>x</b>"

    def _repr_markdown_(self):
        return "**x**"


class Declines:
    def _repr_html_(self):
        return None

    def _repr_svg_(self):
        raise ValueError

    def _repr_png_(self):
        return b"\x89PNG", {"width": 1}


class Magic:
    def __getattr__(self, name):
        return lambda: "<i>nope</i>"

    def __repr__(self):
        return "Magic()"


def test_represent_order_and_fallbacks():
    assert represent(Html()) == ("text/html", "<b>x</b>")
    assert represent(Declines()) == ("image/png", b"\x89PNG")
    assert represent(Html) == ("text/plain", repr(Html))  # the class, not an instance
    assert represent(Magic()) == ("text/plain", "Magic()")
    assert represent([1, "a"]) == ("text/plain", "[1, 'a']")


def last(source):
    _, expr = split_last_expression(source, "doc.md")
    return expr and ast.unparse(expr)


def test_last_expression():
    assert last("x = 1\nx + 1") == "x + 1"
    assert last("x = 1") is None
    assert last("") is None
    assert last("f(\n  1)") == "f(1)"
    assert last("x  # comment;") == "x"


def test_semicolon_silences():
    assert last("x;") is None
    assert last("x ;  # quiet") is None
    assert last("'ñandú';") is None  # end_col_offset counts UTF-8 bytes
    assert last("x = 1; y") == "y"
