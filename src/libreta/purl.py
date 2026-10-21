"""The document as a Python script, as knitr's purl: the code of its blocks in order, the
prose as comments, the imports of every block together at the top (DESIGN §8).

A script runs top to bottom, so the document must too: every name a block uses at module
level has to be defined above it. The editor can run blocks out of order and hide that
(an older version of a block left a name behind); purl checks it in the code itself.
"""

import ast
import builtins
import sys
from pathlib import Path

from libreta.document import front_params, front_value, parse, split_front_matter
from libreta.i18n import tr

KNOWN = set(dir(builtins)) | {"__file__", "__builtins__"}
DEFERRED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def purl(text: str, directory: Path) -> tuple[str, list[str]]:
    """The script of the document `text`, whose folder is `directory` (to tell its own
    modules from installed ones); and the problems that keep it from being one, with their
    line in the .md (no script then: "")."""
    front, body = split_front_matter(text)
    offset = front.count("\n")
    params = front_params(front)
    defined = KNOWN | ({"params"} if params else set())
    problems: list[str] = []
    imports: dict[str, tuple] = {}  # source -> sort key
    parts = []
    for block in parse(body):
        if block.kind == "markdown":
            prose = block.text.strip("\n")
            if prose.strip():
                parts.append("\n".join(f"# {line}".rstrip() for line in prose.splitlines()))
            continue
        first = block.line + offset  # the fence's line in the .md; code line n is first + n
        try:
            tree = ast.parse(block.code)
        except SyntaxError as e:
            problems.append(tr("línea {line}: error de sintaxis", line=first + (e.lineno or 1)))
            continue
        for node in _undefined(tree.body, defined):
            problems.append(_undefined_name(node.id, first + node.lineno))
        hoisted = set()
        for stmt in _hoistable(tree.body):
            imports[ast.unparse(stmt)] = _sort_key(stmt, directory)
            hoisted.update(range(stmt.lineno, stmt.end_lineno + 1))
        lines = block.code.splitlines()
        code = "\n".join(s for n, s in enumerate(lines, 1) if n not in hoisted).strip("\n")
        if code:
            parts.append(code)
    if problems:
        return "", problems
    head = []
    if title := front_value(front, "title"):
        head.append(f"# {title}")
    groups: dict[int, list[str]] = {}
    for source in sorted(imports, key=imports.get):
        groups.setdefault(imports[source][0], []).append(source)
    head += ["\n".join(group) for group in groups.values()]
    if params:
        head.append(f"params = {params!r}")
    return "\n\n".join(head + parts) + "\n", []


def _undefined_name(name: str, line: int) -> str:
    if name == "display":
        return tr("línea {line}: «{name}» solo existe dentro de libreta", line=line, name=name)
    return tr("línea {line}: «{name}» no está definido en ese punto", line=line, name=name)


def _undefined(stmts: list[ast.stmt], defined: set[str]) -> list[ast.Name]:
    """The names `stmts` use, run in order, before anything defines them; `defined` grows
    with what they define. Every branch is taken as run (lenient).
    ponytail: function bodies are not followed (they run when called): a function that uses
    a name defined after the call passes; follow the calls if that ever matters."""
    missing = []

    def use(nodes):
        for node in nodes:
            names = _Names()
            names.visit(node)
            if names.star:  # `from x import *`: from here on, anything may exist
                defined.add("*")
            missing.extend(n for n in names.loads if n.id not in defined and "*" not in defined)
            defined.update(names.binds)

    for stmt in stmts:
        match stmt:
            case ast.If(test=test) | ast.While(test=test):
                use([test])
                missing.extend(_undefined(stmt.body + stmt.orelse, defined))
            case ast.For(target=target, iter=it) | ast.AsyncFor(target=target, iter=it):
                use([it, target])
                missing.extend(_undefined(stmt.body + stmt.orelse, defined))
            case ast.With(items=items) | ast.AsyncWith(items=items):
                use([i.context_expr for i in items])
                use([i.optional_vars for i in items if i.optional_vars])
                missing.extend(_undefined(stmt.body, defined))
            case ast.Try() | ast.TryStar():
                missing.extend(_undefined(stmt.body, defined))
                for handler in stmt.handlers:
                    use([handler.type] if handler.type else [])
                    if handler.name:
                        defined.add(handler.name)
                    missing.extend(_undefined(handler.body, defined))
                missing.extend(_undefined(stmt.orelse + stmt.finalbody, defined))
            case ast.Match(subject=subject, cases=cases):
                use([subject])
                for case in cases:
                    use([case.pattern, *([case.guard] if case.guard else [])])
                    missing.extend(_undefined(case.body, defined))
            case ast.AugAssign(target=ast.Name() as target):  # x += 1 reads x first
                use([ast.Name(target.id, ast.Load(), lineno=target.lineno), stmt])
            case _:
                use([stmt])
    return missing


class _Names(ast.NodeVisitor):
    """The names a statement loads and binds at module level, as it runs now: function
    bodies run later, and comprehensions and class bodies keep their names to themselves."""

    def __init__(self):
        self.loads: list[ast.Name] = []
        self.binds: set[str] = set()
        self.star = False

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.loads.append(node)
        else:
            self.binds.add(node.id)

    def visit_FunctionDef(self, node):
        if not isinstance(node, ast.Lambda):
            self.binds.add(node.name)
            for decorator in node.decorator_list:
                self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)

    visit_AsyncFunctionDef = visit_Lambda = visit_FunctionDef

    def visit_ClassDef(self, node):
        for item in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(item)
        self._inner(node.body)
        self.binds.add(node.name)

    def _comprehension(self, node):
        self._inner([node])

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comprehension

    def _inner(self, nodes):
        """A scope of its own: its loads count, unless it binds them itself."""
        inner = _Names()
        for node in nodes:
            inner.generic_visit(node) if isinstance(node, COMPREHENSIONS) else inner.visit(node)
        self.loads += [n for n in inner.loads if n.id not in inner.binds]

    def visit_Import(self, node):
        for alias in node.names:
            self.binds.add(alias.asname or alias.name.partition(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                self.star = True
            else:
                self.binds.add(alias.asname or alias.name)

    def visit_MatchAs(self, node):
        if node.name:
            self.binds.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.binds.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.binds.add(node.rest)
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        self.binds.add(node.target.id)


def _hoistable(stmts: list[ast.stmt]) -> list[ast.stmt]:
    """The block's top-level imports alone on their lines: those go to the top of the
    script (one inside an `if` or a `try`, or sharing a line, stays where it is).
    ponytail: an import that needs the code above it (sys.path.insert) moves anyway;
    leave such ones in place if they show up."""
    spans = [(s.lineno, s.end_lineno) for s in stmts]
    return [
        s
        for s in stmts
        if isinstance(s, (ast.Import, ast.ImportFrom))
        and sum(a <= s.end_lineno and s.lineno <= b for a, b in spans) == 1
    ]


def _sort_key(stmt: ast.Import | ast.ImportFrom, directory: Path) -> tuple:
    """As isort and ruff: __future__, the standard library, installed packages, the
    document's own modules; in each, `import x` before `from x import y`, by module."""
    if isinstance(stmt, ast.ImportFrom):
        module, level = stmt.module or "", stmt.level
    else:
        module, level = stmt.names[0].name, 0
    top = module.partition(".")[0]
    if module == "__future__":
        group = 0
    elif level or (directory / f"{top}.py").is_file() or (directory / top).is_dir():
        group = 3
    elif top in sys.stdlib_module_names:
        group = 1
    else:
        group = 2
    return group, isinstance(stmt, ast.ImportFrom), module.lower(), ast.unparse(stmt)
