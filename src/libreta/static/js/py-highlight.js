// Python tokenizer for the overlay. Colours only (DESIGN §6.2). One regex pass over the
// whole block: a triple-quoted string spanning lines is a single match, so no state is
// carried by hand. f-strings are coloured whole as strings (v1). Imports of modules the
// environment lacks are greyed out (setModules).

const KEYWORDS = new Set(
  ("False None True and as assert async await break class continue def del elif else " +
    "except finally for from global if import in is lambda nonlocal not or pass raise " +
    "return try while with yield").split(" "),
);

const BUILTINS = new Set(
  ("abs aiter all anext any ascii bin bool breakpoint bytearray bytes callable chr " +
    "classmethod compile complex delattr dict dir divmod enumerate eval exec filter float " +
    "format frozenset getattr globals hasattr hash help hex id input int isinstance " +
    "issubclass iter len list locals map max memoryview min next object oct open ord pow " +
    "print property range repr reversed round set setattr slice sorted staticmethod str " +
    "sum super tuple type vars zip __import__ __name__ __file__ self cls NotImplemented " +
    "Ellipsis Exception BaseException ArithmeticError AssertionError AttributeError " +
    "EOFError ImportError IndexError KeyError KeyboardInterrupt LookupError NameError " +
    "NotImplementedError OSError RuntimeError StopIteration SystemExit TypeError " +
    "ValueError ZeroDivisionError FileNotFoundError ModuleNotFoundError Warning").split(" "),
);

const TOKEN = new RegExp(
  [
    String.raw`(?<com>#[^\n]*)`,
    String.raw`(?<str>[rRbBuUfFtT]{0,2}(?:'''[^]*?(?:'''|$)|"""[^]*?(?:"""|$)|'(?:\\[^]|[^'\\\n])*'?|"(?:\\[^]|[^"\\\n])*"?))`,
    String.raw`(?<deco>@[\p{L}_][\p{L}\p{N}_.]*)`,
    String.raw`(?<num>0[xXoObB][\da-fA-F_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?[jJ]?)`,
    String.raw`(?<name>[\p{L}_][\p{L}\p{N}_]*)`,
    String.raw`(?<other>\s+|[^])`,
  ].join("|"),
  "gu",
);

let modules = null; // Set of importable top-level modules; null: unknown, nothing greyed

export function setModules(names) {
  modules = names ? new Set(names) : null; // null: the server could not tell
}

export function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function highlightPython(text) {
  let html = "";
  let prev = ""; // previous significant token
  let importing = null; // "import", "from" (module next) or "names" (from x import ...)
  TOKEN.lastIndex = 0;
  for (let m; (m = TOKEN.exec(text)); ) {
    const g = m.groups;
    let value = m[0];
    let cls = null;
    if (g.com) cls = "com";
    else if (g.str) cls = "str";
    else if (g.num) cls = "num";
    else if (g.deco) {
      if (atLineStart(text, m.index)) cls = "deco";
      else {
        value = "@"; // the matrix-multiplication operator
        TOKEN.lastIndex = m.index + 1;
      }
    } else if (g.name) {
      cls = nameClass(value, prev, text, m.index);
      const head = importing === "from" ? prev === "from" : importing === "import" && /^(import|,)$/.test(prev);
      if (head && modules && !modules.has(value)) cls = "missing"; // first name of a.b.c
      if (value === "import") importing = importing === "from" ? "names" : "import";
      else if (value === "from" && atLineStart(text, m.index)) importing = "from"; // not yield from
    } else if (importing && /[\n;]/.test(value)) importing = null;
    html += cls ? `<span class="tok-${cls}">${escapeHtml(value)}</span>` : escapeHtml(value);
    if (!g.com && !/^\s/.test(value)) prev = value;
  }
  return html;
}

function nameClass(name, prev, text, index) {
  if (prev === "def" || prev === "class") return "def";
  if (prev === ".") return null; // attribute: df.sum is not the builtin sum
  if (KEYWORDS.has(name)) return "kw";
  if ((name === "match" || name === "case" || name === "type") && isSoftKeyword(name, text, index))
    return "kw";
  if (BUILTINS.has(name)) return "builtin";
  return null;
}

// `match x:` / `case _: pass` open a line, are followed by an operand (not by `=`, `.`...)
// and have a ':'; `type X = ...` is an alias statement.
function isSoftKeyword(name, text, index) {
  if (!atLineStart(text, index)) return false;
  const end = text.indexOf("\n", index);
  const rest = text.slice(index + name.length, end < 0 ? undefined : end);
  if (name === "type") return /^\s+[\p{L}_][\p{L}\p{N}_]*\s*(\[.*\])?\s*=/u.test(rest);
  return /^\s+[^\s=.,:)\]}]/.test(rest) && rest.includes(":");
}

function atLineStart(text, index) {
  return /^[ \t]*$/.test(text.slice(text.lastIndexOf("\n", index - 1) + 1, index));
}
