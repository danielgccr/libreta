import argparse
import secrets
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

import uvicorn

from libreta.app import create_app
from libreta.cache import GENESIS, Cache, chain
from libreta.document import expressions, front_value, parse, split_front_matter
from libreta.knit import complete, knit, remove_figures
from libreta.worker import Worker

HERE = Path(__file__).parent
STREAMS = {"stdout", "stderr", "error"}
STDERR = {"stderr", "error"}
VALUES = {"text/plain", "text/markdown"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="libreta")
    commands = parser.add_subparsers(dest="command")  # none: the index of this folder
    edit_parser = commands.add_parser("edit", help="open a document (or a folder's index)")
    edit_parser.add_argument("path", type=Path)
    run_parser = commands.add_parser("run", help="run a document top to bottom")
    run_parser.add_argument("path", type=Path)
    export_parser = commands.add_parser("export", help="knit the document and convert it")
    export_parser.add_argument("path", type=Path)
    export_parser.add_argument("--to", choices=["html", "pdf"], default="html")
    export_parser.add_argument(
        "--css", type=Path, action="append", default=[], help="extra style sheet (HTML)"
    )
    export_parser.add_argument(
        "--keep-md", action="store_true", help="keep the knitted Markdown and its figures"
    )
    args = parser.parse_args(argv)
    if args.command == "run":
        return run(args.path)
    if args.command == "export":
        return export(args.path, args.to, args.css, args.keep_md)
    if args.command is None or args.path.is_dir():
        serve(args.path if args.command else Path.cwd())
    elif args.path.suffix != ".md":
        print(f"libreta: {args.path} no es un fichero .md", file=sys.stderr)
        return 2
    else:
        serve(args.path.parent, args.path.name)
    return 0


def run(path: Path, keep_going: bool = False) -> int:
    """Run every block in a fresh worker, caching its output; stop at the first error
    (exit status 1), or with `keep_going` run the rest anyway."""
    if not path.is_file():
        print(f"libreta: no existe {path}", file=sys.stderr)
        return 2
    source = path.read_text(encoding="utf-8")
    parsed = parse(source)
    blocks = [b for b in parsed if b.kind == "python"]
    exprs = expressions(parsed)
    keys = [GENESIS, *chain(b.code for b in blocks)]
    cache = Cache(path)
    cache.prune(set(keys))
    worker = Worker(path)

    def evaluate(i: int) -> bool:
        """The `py` expressions after block i - 1; False if any of them fails."""
        if not exprs[i]:
            return True
        values = worker.inline(exprs[i], source)
        cache.save_values(keys[i], values)
        failed = [expr for expr in exprs[i] if "text" not in values.get(expr, {})]
        for expr in failed:  # a dead worker gives no values at all
            print(f"`py {expr}`: {values.get(expr, {}).get('error')}", file=sys.stderr)
        return not failed

    status = 0
    try:
        if not evaluate(0):
            status = 1
            if not keep_going:
                return status
        for i, (block, h) in enumerate(zip(blocks, keys[1:], strict=True)):
            items = []
            for mime, content in worker.run(block.code, block.line + 1, source):
                items.append((mime, content))
                out = sys.stderr if mime in STDERR else sys.stdout
                if mime not in STREAMS:
                    content = (content if mime in VALUES else f"[{mime}]") + "\n"
                out.write(content)
                out.flush()  # keep stdout and stderr interleaved when redirected
            cache.save(h, items)
            if any(mime == "error" for mime, _ in items) or not evaluate(i + 1):
                status = 1
                if not keep_going:
                    return status
    except KeyboardInterrupt:
        return 130
    finally:
        worker.close()
    return status


def export(path: Path, to: str, css: list[Path], keep_md: bool = False) -> int:
    """Knit the document from its cache (running it first if the cache is incomplete) into
    <name>.knit.md, and convert that with Pandoc when it is installed (DESIGN §10). The
    knitted Markdown and its figures go once converted (the output embeds them), unless
    `keep_md`; without Pandoc, or if it fails, they are what is left.
    Errors stay in the document, as in the editor; they make the exit status 1."""
    for file in [path, *css]:
        if not file.is_file():
            print(f"libreta: no existe {file}", file=sys.stderr)
            return 2
    if not complete(path):
        print(f"libreta: la caché no está completa; se ejecuta {path}", file=sys.stderr)
        if run(path, keep_going=True) == 130:
            return 130
    markdown, problems = knit(path)
    for problem in problems:
        print(f"libreta: {problem}", file=sys.stderr)
    knitted = path.with_name(f"{path.stem}.knit.md")
    knitted.write_text(markdown, encoding="utf-8")
    if shutil.which("pandoc") is None:
        print(f"libreta: sin Pandoc; el Markdown tejido está en {knitted}", file=sys.stderr)
        return 1 if problems else 0
    output = path.with_suffix(f".{to}")
    command = ["pandoc", knitted.name, "--from", "commonmark_x", "--output", output.name]
    if not front_value(split_front_matter(markdown)[0], "title"):
        command += ["--metadata", f"pagetitle={path.stem}"]  # else Pandoc takes the title
    engine = None
    if to == "pdf":  # WeasyPrint follows export.css; typst lays the page out on its own
        engine = "weasyprint" if shutil.which("weasyprint") else "typst"
        command += ["--pdf-engine", engine]
    if to == "html" or engine == "weasyprint":
        command += ["--to", "html5", "--standalone", "--embed-resources", _mathml()]
        command += ["--template", str(HERE / "templates" / "export.html")]
        sheets = [HERE / "static" / "css" / "tokens.css", HERE / "static" / "css" / "export.css"]
        for sheet in [*sheets, *css]:
            command += ["--css", str(sheet.resolve())]
    if status := subprocess.run(command, cwd=path.parent).returncode:
        return status
    if not keep_md:
        knitted.unlink()
        remove_figures(path)
    print(f"libreta: {output}")
    return 1 if problems else 0


def _mathml() -> str:
    """Pandoc's MathML option: --math-method in recent versions, which warn about --mathml;
    older ones only know --mathml."""
    help_text = subprocess.run(["pandoc", "--help"], capture_output=True, text=True).stdout
    return "--math-method=mathml" if "--math-method" in help_text else "--mathml"


def serve(root: Path, document: str | None = None) -> None:
    """Serve the documents under `root` and open the browser on `document`, or on the index."""
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()  # queue the browser's first request until uvicorn starts accepting
    page = f"edit/{quote(document)}" if document else ""
    url = f"http://127.0.0.1:{sock.getsockname()[1]}/{page}?token={token}"
    print(f"libreta: {root / (document or '')} en {url}", flush=True)
    webbrowser.open(url)
    server = uvicorn.Server(uvicorn.Config(create_app(root, token), log_level="warning"))
    try:
        server.run([sock])
    except KeyboardInterrupt:  # uvicorn re-raises Ctrl+C after shutting down cleanly
        pass
