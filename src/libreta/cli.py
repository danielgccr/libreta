import argparse
import secrets
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn

from libreta.app import create_app
from libreta.cache import GENESIS, Cache, chain
from libreta.document import expressions, parse
from libreta.worker import Worker

STREAMS = {"stdout", "stderr", "error"}
STDERR = {"stderr", "error"}
VALUES = {"text/plain", "text/markdown"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="libreta")
    commands = parser.add_subparsers(dest="command", required=True)
    edit_parser = commands.add_parser("edit", help="open a document in the browser editor")
    edit_parser.add_argument("path", type=Path)
    run_parser = commands.add_parser("run", help="run a document top to bottom")
    run_parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        return run(args.path)
    edit(args.path)
    return 0


def run(path: Path) -> int:
    """Run every block in a fresh worker, caching its output; stop at the first error
    (exit status 1)."""
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

    try:
        if not evaluate(0):
            return 1
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
                return 1
    except KeyboardInterrupt:
        return 130
    finally:
        worker.close()
    return 0


def edit(path: Path) -> None:
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()  # queue the browser's first request until uvicorn starts accepting
    url = f"http://127.0.0.1:{sock.getsockname()[1]}/?token={token}"
    print(f"libreta: {path} en {url}", flush=True)
    webbrowser.open(url)
    server = uvicorn.Server(uvicorn.Config(create_app(path, token), log_level="warning"))
    try:
        server.run([sock])
    except KeyboardInterrupt:  # uvicorn re-raises Ctrl+C after shutting down cleanly
        pass
