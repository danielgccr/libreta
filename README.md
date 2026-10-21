# libreta

A prose-first Python notebook. You get a blank page where you write Markdown and, when
you need it, drop in a Python block that runs and shows its output right there: text,
tables, matplotlib figures, errors.

Its lineage is RMarkdown and knitr, not Jupyter: it is for writing a document whose numbers
come from code, not for exploring. The file is plain Markdown, so GitHub, Obsidian and
Pandoc read it without knowing libreta exists, and git diffs it line by line.

````markdown
# Mean age of the sample

```python
import pandas as pd
df = pd.read_csv("census.csv")
df.head()
```

The mean age is `py round(df.age.mean(), 1)` years.
````

The interface and its messages are in Spanish.

## Installation

Requires Python 3.12 or later, on Linux or macOS.

```sh
uv tool install libreta
```

or with pip, `pip install libreta`.

Optional:

- [Pandoc](https://pandoc.org), to export to HTML or PDF.
- WeasyPrint or typst, for PDF.
- matplotlib, pandas and the like are not bundled: libreta uses whatever the document's
  environment has installed.

## Usage

```sh
libreta                     # list the .md files in the current folder, in the browser
libreta edit report.md      # open a document (if it does not exist, saving creates it)
libreta edit folder/        # list the .md files in another folder
libreta run report.md       # run it top to bottom, no browser
libreta export report.md    # report.html (with --to pdf, report.pdf)
libreta purl report.md      # the document as a Python script, on stdout
```

The server listens only on `127.0.0.1` and requires a random token in the URL, since it
runs arbitrary code. Stop it with Ctrl+C in the terminal.

### The Python environment

A document's code runs with its project's Python, with nothing to configure: the nearest
`.venv` going up from the document's folder; failing that, the activated environment
(`VIRTUAL_ENV`); failing that, libreta's own. To use pandas in a document, have it in that
project's `.venv` (`uv add pandas`). libreta prints which Python it uses on startup.

### Writing

Everything is raw Markdown: there is no edit mode and render mode. A Python block is a
top-level ` ```python ` fence; any other fence is text and does not run.

| Shortcut | Effect |
|---|---|
| Ctrl+Alt+I | Insert a Python block (splits the paragraph at the cursor) |
| Ctrl+Enter | Run the block and move to the text below; in Markdown, evaluate its `` `py …` `` |
| Escape | Interrupt the running block |
| Ctrl+Shift+F10 | Restart Python with an empty namespace |
| Ctrl+Space | Autocomplete (it also pops up as you type) |
| Ctrl+Alt+F | Insert a footnote `[^n]` with its definition |
| Ctrl+/ | Comment or uncomment Python lines |
| Ctrl+A / Ctrl+C | Select and copy the whole document as Markdown |
| Ctrl+S | Save |

The title and date live in the YAML front matter (`title`, `date`) and are edited above
the document; the date is set on save.

### Running

- The document runs top to bottom, as in knitr: if you run block 5 and block 2 has
  changed, libreta restarts Python and runs 1 to 5. If only block 5 changed, it reruns it
  on the current state. Later blocks are marked as stale.
- A block's last expression is displayed (unless it ends in `;`). Any object with
  `_repr_html_`, `_repr_png_`, `_repr_svg_`… displays properly: pandas and polars
  DataFrames, sympy, Altair. `display(obj)` shows something mid-block.
- matplotlib figures appear on their own, no `plt.show()` needed.
- Top-level `await` works.
- `` `py expr` `` inside the text is an expression that gets evaluated; its value shows in
  the right margin and, on export, replaces the expression.

### Cache

Outputs are not stored in the `.md`: they live in `.libreta/<document>/` next to the
document, keyed by a chained hash of the blocks. Opening a document shows the outputs of
its last run without running anything; changing a block invalidates it and the ones after.
The data counts too: libreta notes the files each block reads (`open()`, pandas, and paths
named in the code, for parquet, polars or duckdb), and if one changes on disk the block and
the ones after it are stale; running a later block starts again from the top.
The folder is disposable: add it to `.gitignore` or commit it.

### Params

As in RMarkdown, the front matter can declare params, which the code reads from a `params`
dict:

```yaml
---
title: Monthly report
params:
  month: 2026-09
  threshold: 0.5
---
```

The editor runs with these values; `libreta run` and `libreta export` take others with
`-p month=2026-10` (once per param).

### `libreta run`

Runs the document in a fresh process, updates the cache and reports errors with their line
in the `.md`. It exits non-zero if any block fails, so it works in cron or CI.

### `libreta purl`

```sh
libreta purl report.md > report.py
```

The document as a Python script, as knitr's `purl`: the blocks' code in order, the prose as
comments, and every top-level import gathered at the top, sorted as isort does. A script
runs top to bottom, so first it checks the document does too: a name used above the block
that defines it (easy to miss when blocks ran out of order in the editor) is reported with
its line, and no script is written.

### `libreta export`

```sh
libreta export report.md                  # report.html, self-contained
libreta export report.md --to pdf         # report.pdf
libreta export report.md --css mine.css   # style tweaks on top of libreta's
libreta export report.md --keep-md        # keep the intermediate Markdown
```

Knits the document from its cache (running it first if anything is missing) and converts
it with Pandoc. Without Pandoc, it leaves `report.knit.md`, Markdown with the outputs
embedded.

## Development

```sh
uv sync
uv run libreta edit ejemplos/demo.md
uv run pytest
uv run ruff check . && uv run ruff format .
```

The backend is Starlette, uvicorn and jedi. The editor is dependency-free
JavaScript with no build step: textareas over a highlighted overlay, with hand-written
tokenizers. The full design and its reasoning are in [docs/DESIGN.md](docs/DESIGN.md)
(in Spanish).

## License

[GNU GPL v3](LICENSE) or later.
