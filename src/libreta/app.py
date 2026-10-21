"""Starlette app for the editor. It runs arbitrary code, so every request must come from
localhost (Host header, against DNS rebinding) and carry the session token."""

import contextlib
import importlib.metadata
import json
import os
import pkgutil
import secrets
import shutil
import sys
import threading
from datetime import date
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from libreta.cache import GENESIS, Cache, chain, to_json
from libreta.document import (
    Block,
    code_at,
    expressions,
    front_value,
    parse,
    split_front_matter,
    stamp,
)
from libreta.worker import Worker

HERE = Path(__file__).parent
COOKIE = "libreta_token"
templates = Jinja2Templates(HERE / "templates")


class TokenMiddleware:
    """Accept ``?token=`` once (set the cookie and redirect without it), then the cookie."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    def valid(self, candidate: str) -> bool:
        return secrets.compare_digest(candidate.encode(), self.token)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if self.valid(request.cookies.get(COOKIE, "")):
            return await self.app(scope, receive, send)
        if self.valid(request.query_params.get("token", "")):
            response = RedirectResponse(request.url.remove_query_params("token"), 303)
            response.set_cookie(COOKIE, self.token.decode(), httponly=True, samesite="strict")
        else:
            response = PlainTextResponse("Forbidden", 403)
        await response(scope, receive, send)


class RevalidatedStaticFiles(StaticFiles):
    """Always revalidate: a browser must never run last milestone's cached editor."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def editor_blocks(text: str, cache: Cache | None = None) -> list[dict]:
    """What each editor block shows. A block's last line ending is implied, not shown:
    the client adds it back when serializing (see serialize() in blocks.js).
    With a cache, Python blocks also carry their cached output and the values of the Markdown
    after them (None if there are none)."""
    parsed = parse(text)
    hashes = iter(chain(b.code for b in parsed if b.kind == "python"))
    blocks = []
    for block in parsed:
        if block.kind == "markdown":
            blocks.append({"kind": "markdown", "value": _chop(block.text)})
        else:
            head, newline, _ = block.text.partition("\n")
            opening = head + newline
            body = block.text[len(opening) : len(block.text) - len(block.close)]
            item = {"kind": "python", "value": _chop(body), "open": opening, "close": block.close}
            h = next(hashes)
            if cache is not None:
                item["output"] = cache.load(h)
                item["values"] = cache.load_values(h)
            blocks.append(item)
    return blocks


def modules(directory: Path) -> list[str]:
    """Top-level modules the document can import: the worker runs this same interpreter,
    from the document's folder. The editor greys out imports of anything else.
    Distributions' names too: namespace packages and editable installs with import hooks
    escape iter_modules."""
    names = set(sys.builtin_module_names)
    names.update(m.name for m in pkgutil.iter_modules([str(directory), *sys.path]))
    names.update(importlib.metadata.packages_distributions())
    return sorted(names)


def _chop(text: str) -> str:
    return text[:-1] if text.endswith("\n") else text


def save(path: Path, text: str) -> None:
    """Atomic write that keeps the file's line endings (the editor only speaks \\n)."""
    target = path.resolve()  # write through a symlink, do not replace it
    if target.exists() and b"\r\n" in target.read_bytes():
        text = text.replace("\n", "\r\n")
    tmp = target.with_name(f".{target.name}.libreta-tmp")
    tmp.write_bytes(text.encode())
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


class Session:
    """The document's worker: created on first use, one block running at a time.

    `state` is (before, after): the worker's namespace reflects the chain up to hash
    `after`, reached by running one last block on top of `before` (DESIGN §4.5)."""

    def __init__(self, path: Path):
        self.path = path
        self.cache = Cache(path)
        self.worker: Worker | None = None
        self.state = (GENESIS, GENESIS)
        self.lock = threading.Lock()  # held while a block runs; later runs queue on it
        self.interrupted = False  # Escape during the current run

    def run(self, text: str, parsed: list[Block], n: int, inline: bool = False):
        """Run the n-th Python block of `text` on the state the blocks before it leave, and
        evaluate the `py` expressions of the Markdown after it. With `inline`, only bring the
        worker to the n-th point of the document (0: before the first block) and evaluate
        the expressions there.

        A blocking generator of NDJSON lines (Starlette iterates it in a thread):
        ``{"start": line}`` before the output of each block that runs, then its items, and
        ``{"values": {...}, "line": line}`` for the Markdown after the block at `line`
        (0: before the first one)."""
        blocks = [b for b in parsed if b.kind == "python"]
        exprs = expressions(parsed)
        keys = [GENESIS, *chain(b.code for b in blocks)]  # keys[i]: the state before block i
        target = n - 1 if inline else n  # last block to run; -1: none

        def evaluate(i):  # the Markdown at point i, after block i - 1
            if exprs[i]:
                values = self.worker.inline(exprs[i], text)
                self.cache.save_values(keys[i], values)
                yield _ndjson({"values": values, "line": blocks[i - 1].line if i else 0})

        with self.lock:
            self.interrupted = False
            self.cache.prune(set(keys))
            alive = self.worker is not None and self.worker.process.is_alive()
            if inline and alive and self.state[1] == keys[n]:  # already there: only evaluate
                yield from evaluate(n)
                return
            # Same blocks before it: run on the current state (even over an older version
            # of itself, impure and accepted). Else, as knitr: a new worker runs 1..N.
            fresh = not alive or target < 0 or keys[target] not in self.state
            if fresh:
                self._new_worker()
                yield from evaluate(0)
            for i in range(0 if fresh else target, target + 1):
                # An error in an earlier block does not stop the rest (the editor is
                # pragmatic, `libreta run` is not); Escape does.
                if self.interrupted:
                    yield _ndjson({"start": blocks[target].line})
                    yield _ndjson(to_json("error", "No se ha ejecutado: interrumpido.\n"))
                    return
                block = blocks[i]
                yield _ndjson({"start": block.line})
                self.state = (keys[i], keys[i + 1])
                items = []
                for mime, content in self.worker.run(block.code, block.line + 1, text):
                    items.append((mime, content))
                    yield _ndjson(to_json(mime, content))
                self.cache.save(keys[i + 1], items)  # only once complete, never if abandoned
                if not self.interrupted:
                    yield from evaluate(i + 1)

    def assist(self, kind: str, code: str, line: int, column: int) -> list[dict]:
        """Completions or signatures from jedi in the worker (see Worker.assist)."""
        if not self.lock.acquire(blocking=False):  # ponytail: no help while a block runs
            return []
        try:
            if self.worker is None or not self.worker.process.is_alive():
                self._new_worker()
            return self.worker.assist(kind, code, line, column)
        finally:
            self.lock.release()

    def _new_worker(self) -> None:
        if self.worker is not None:
            self.worker.close()
        self.worker = Worker(self.path)
        self.state = (GENESIS, GENESIS)

    def interrupt(self) -> None:
        self.interrupted = True
        if self.worker is not None and self.worker.process.is_alive():
            self.worker.interrupt()

    def restart(self) -> None:
        """Kill the worker (a running block ends at once); the next run starts a fresh one."""
        worker = self.worker
        if worker is not None:
            worker.process.kill()
        with self.lock:
            if worker is not None:
                worker.close()
            if self.worker is worker:
                self.worker = None


def _ndjson(item: dict) -> str:
    return json.dumps(item) + "\n"


def create_app(path: Path, token: str) -> Starlette:
    session = Session(path)

    async def editor(request: Request):
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # The browser only speaks \n; save() restores \r\n files.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # The front matter is no block: the editor shows its title and date above them.
        front, body = split_front_matter(text)
        doc = {
            "blocks": editor_blocks(body, session.cache),
            "finalNewline": text == "" or text.endswith("\n"),
            "values": session.cache.load_values(GENESIS),  # Markdown before the first block
            "front": front,
            "title": front_value(front, "title") or "",
            "date": front_value(front, "date"),
            "modules": modules(path.parent.resolve()),  # again on focus: GET /modules
        }
        return templates.TemplateResponse(request, "editor.html", {"name": path.name, "doc": doc})

    async def put_doc(request: Request):
        """{text, title} -> the text as saved, its front matter and date: saving sets the
        title and stamps the day in the front matter."""
        data = await request.json()
        text = stamp(data["text"], data["title"].strip(), date.today().isoformat())
        save(path, text)
        front, _ = split_front_matter(text)
        return JSONResponse({"text": text, "front": front, "date": front_value(front, "date")})

    async def run(request: Request):
        """Run the Python block whose fence opens at `line` of `text` (the unsaved document:
        the server reparses it rather than trusting the client's idea of the blocks)."""
        data = await request.json()
        text, line, inline = data["text"], data["line"], data.get("inline", False)
        parsed = parse(text)
        blocks = [b for b in parsed if b.kind == "python"]
        if inline:  # Markdown at `line`: the point after the Python blocks above it
            n = sum(b.line < line for b in blocks)
        else:
            n = next((i for i, b in enumerate(blocks) if b.line == line), None)
            if n is None:
                return PlainTextResponse("No hay un bloque de Python en esa línea.", 409)
        lines = session.run(text, parsed, n, inline)
        return StreamingResponse(lines, media_type="application/x-ndjson")

    async def assist(request: Request):
        """POST /complete and /signature: {text, line, column} -> JSON list (DESIGN §6.6)."""
        data = await request.json()
        point = code_at(data["text"], data["line"], data["column"])
        if point is None:
            return JSONResponse([])
        kind = request.url.path.strip("/")
        return JSONResponse(await run_in_threadpool(session.assist, kind, *point))

    async def get_modules(request: Request):
        return JSONResponse(await run_in_threadpool(modules, path.parent.resolve()))

    async def interrupt(request: Request):
        session.interrupt()
        return Response(status_code=204)

    async def restart(request: Request):
        await run_in_threadpool(session.restart)
        return Response(status_code=204)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        yield
        await run_in_threadpool(session.restart)  # else multiprocessing waits for the child

    return Starlette(
        routes=[
            Route("/", editor),
            Route("/doc", put_doc, methods=["PUT"]),
            Route("/run", run, methods=["POST"]),
            Route("/complete", assist, methods=["POST"]),
            Route("/signature", assist, methods=["POST"]),
            Route("/modules", get_modules),
            Route("/interrupt", interrupt, methods=["POST"]),
            Route("/restart", restart, methods=["POST"]),
            Mount("/static", RevalidatedStaticFiles(directory=HERE / "static"), name="static"),
        ],
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]),
            Middleware(TokenMiddleware, token=token),
        ],
        lifespan=lifespan,
    )
