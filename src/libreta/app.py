"""Starlette app for the editor. It runs arbitrary code, so every request must come from
localhost (Host header, against DNS rebinding) and carry the session token."""

import contextlib
import html
import json
import os
import secrets
import shutil
import subprocess
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

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
from libreta.worker import Worker, environment

HERE = Path(__file__).parent
COOKIE = "libreta_token"
# JSON inside <script>: no "</script>" or "<!--" in the document can end it.
SCRIPT_SAFE = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"})


def page(template: str, status: int = 200, /, **values: str) -> HTMLResponse:
    """templates/<template> with its $placeholders filled; the values go in already escaped."""
    text = (HERE / "templates" / template).read_text(encoding="utf-8")
    return HTMLResponse(Template(text).substitute(values), status_code=status)


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
    With a cache, Python blocks also carry their cached output, the values of the Markdown
    after them (None if there are none) and whether the data they read has changed since
    (and with it, every block after them)."""
    parsed = parse(text)
    hashes = iter(chain(b.code for b in parsed if b.kind == "python"))
    blocks = []
    stale = False
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
                stale = item["stale"] = stale or cache.stale(h)
            blocks.append(item)
    return blocks


# Run by the document's Python: importable top-level modules, as JSON. Distributions'
# names too: namespace packages and editable installs with import hooks escape iter_modules.
MODULES = """
import importlib.metadata, json, pkgutil, sys
names = set(sys.builtin_module_names)
names.update(m.name for m in pkgutil.iter_modules([sys.argv[1], *sys.path]))
names.update(importlib.metadata.packages_distributions())
print(json.dumps(sorted(names)))
"""


def modules(directory: Path) -> list[str] | None:
    """Top-level modules the document can import, asked to the Python its worker runs
    (see worker.environment). The editor greys out imports of anything else; None if the
    question fails (then nothing is greyed)."""
    python, env = environment(directory)
    command = [python, "-P", "-c", MODULES, str(directory)]
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=directory)
    return json.loads(result.stdout) if result.returncode == 0 else None


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
            alive = self.worker is not None and self.worker.alive()
            if inline and alive and self.state[1] == keys[n] and not self.cache.stale(keys[n]):
                yield from evaluate(n)  # already there: only evaluate
                return
            # Same blocks before it, reading the same data: run on the current state (even
            # over an older version of itself, impure and accepted). Else, as knitr: a new
            # worker runs 1..N.
            fresh = (
                not alive
                or target < 0
                or keys[target] not in self.state
                or self.cache.stale(keys[target])
            )
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
                # Only once complete, never if abandoned.
                self.cache.save(keys[i + 1], items, self.worker.reads)
                if not self.interrupted:
                    yield from evaluate(i + 1)

    def assist(self, kind: str, code: str, line: int, column: int) -> list[dict]:
        """Completions or signatures from jedi in the worker (see Worker.assist)."""
        if not self.lock.acquire(blocking=False):  # ponytail: no help while a block runs
            return []
        try:
            if self.worker is None or not self.worker.alive():
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
        if self.worker is not None and self.worker.alive():
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


SKIP = {"node_modules", "__pycache__"}  # besides hidden folders (.git, .venv, .libreta)
MONTHS = "ene feb mar abr may jun jul ago sep oct nov dic".split()


def markdown_files(root: Path) -> list[tuple[str, float]]:
    """(path relative to root, modification time) of every Markdown document under root,
    the most recently edited first. ponytail: walks the whole tree on each visit; cap it if
    libreta ever gets opened on a huge folder."""
    found = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP]
        for name in files:
            if name.endswith(".md") and not name.endswith(".knit.md"):
                file = Path(directory, name)
                with contextlib.suppress(OSError):  # a broken symlink
                    found.append((file.relative_to(root).as_posix(), file.stat().st_mtime))
    return sorted(found, key=lambda f: (-f[1], f[0]))


def when(mtime: float, now: datetime | None = None) -> str:
    """A modification time as the index shows it: "hoy, 20:41", "ayer, 9:05", "21 oct",
    "3 mar 2025"."""
    t = datetime.fromtimestamp(mtime)
    now = now or datetime.now()
    if t.date() == now.date():
        return f"hoy, {t.hour}:{t.minute:02}"
    if t.date() == now.date() - timedelta(days=1):
        return f"ayer, {t.hour}:{t.minute:02}"
    day = f"{t.day} {MONTHS[t.month - 1]}"
    return day if t.year == now.year else f"{day} {t.year}"


def create_app(root: Path, token: str) -> Starlette:
    """The editor for the Markdown documents under `root`: their index at /, each one at
    /edit/<path>, with its calls under that same URL. One worker at a time: the document in
    use has it (see `using`), and closing its page closes it (.../restart)."""
    root = Path(os.path.abspath(root))
    sessions: dict[Path, Session] = {}

    def markdown(rel: str) -> Path:
        """Only .md files under root (no way out with "..")."""
        path = Path(os.path.normpath(root / rel))
        if path.suffix != ".md" or not path.is_relative_to(root):
            raise HTTPException(404)
        return path

    def document(request: Request) -> tuple[Path, Session]:
        """The document of the URL."""
        path = markdown(request.path_params["doc"])
        if path not in sessions:
            sessions[path] = Session(path)
        return path, sessions[path]

    async def using(session: Session) -> None:
        """The document about to run code gets the only worker: the others' close."""
        for other in sessions.values():
            if other is not session and other.worker is not None:
                await run_in_threadpool(other.restart)

    async def index(request: Request, name: str = "", error: str = ""):
        """The list; with `error`, the new-document form keeps `name` and says what failed."""
        e = html.escape
        files = []
        for rel, mtime in await run_in_threadpool(markdown_files, root):
            folder, slash, file = rel.rpartition("/")
            iso = datetime.fromtimestamp(mtime).isoformat(timespec="minutes")
            files.append(
                f'<li><a href="/edit/{e(quote(rel))}"><span class="folder">{e(folder + slash)}'
                f'</span>{e(file)}</a><time datetime="{iso}">{e(when(mtime))}</time></li>'
            )
        invalid = ' aria-invalid="true" aria-describedby="new-error" autofocus' if error else ""
        alert = error and f'<p id="new-error" class="new-error" role="alert">{e(error)}</p>'
        empty = '<p class="empty">No hay ficheros Markdown en esta carpeta.</p>'
        return page(
            "index.html",
            400 if error else 200,
            root=e(root.name or str(root)),
            count=f"{len(files)} documento{'' if len(files) == 1 else 's'}",
            name=e(name),
            invalid=invalid,
            error=alert,
            files=f"<ol>{''.join(files)}</ol>" if files else empty,
        )

    async def new(request: Request):
        """The index's form: create the document `name` (".md" optional, folders too) and
        open it. An existing one just opens; a name it cannot take, back to the list."""
        name = parse_qs((await request.body()).decode()).get("name", [""])[0].strip()
        if not name:
            return await index(request, name, "Escribe un nombre para el documento.")
        try:
            path = markdown(name if name.endswith(".md") else name + ".md")
        except HTTPException:
            error = "El documento tiene que quedar dentro de esta carpeta."
            return await index(request, name, error)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.open("a").close()  # not touch(): it would bump an existing one up the list
        except OSError as e:  # a folder with that name, no permission...
            return await index(request, name, f"No se pudo crear: {e.strerror.lower()}.")
        return RedirectResponse("/edit/" + quote(path.relative_to(root).as_posix()), 303)

    async def editor(request: Request):
        path, session = document(request)
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
            "modules": modules(path.parent),  # again on focus: GET .../modules
        }
        return page(
            "editor.html",
            name=html.escape(path.name),
            path=html.escape(path.relative_to(root).as_posix()),
            doc=json.dumps(doc, sort_keys=True).translate(SCRIPT_SAFE),
        )

    async def put_doc(request: Request):
        """{text, title} -> the text as saved, its front matter and date: saving sets the
        title and stamps the day in the front matter."""
        path, _ = document(request)
        data = await request.json()
        text = stamp(data["text"], data["title"].strip(), date.today().isoformat())
        save(path, text)
        front, _ = split_front_matter(text)
        return JSONResponse({"text": text, "front": front, "date": front_value(front, "date")})

    async def run(request: Request):
        """Run the Python block whose fence opens at `line` of `text` (the unsaved document:
        the server reparses it rather than trusting the client's idea of the blocks)."""
        _, session = document(request)
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
        await using(session)
        lines = session.run(text, parsed, n, inline)
        return StreamingResponse(lines, media_type="application/x-ndjson")

    async def assist(request: Request):
        """.../complete and .../signature: {text, line, column} -> JSON list (DESIGN §6.6)."""
        _, session = document(request)
        data = await request.json()
        point = code_at(data["text"], data["line"], data["column"])
        if point is None:
            return JSONResponse([])
        kind = request.url.path.rpartition("/")[2]
        await using(session)
        return JSONResponse(await run_in_threadpool(session.assist, kind, *point))

    async def stale_line(request: Request):
        """{text} -> the line of the first Python block whose data changed on disk, or null:
        the editor fades it and the ones after it (asked when the window gets focus back)."""
        _, session = document(request)
        blocks = [b for b in parse((await request.json())["text"]) if b.kind == "python"]
        for block, h in zip(blocks, chain(b.code for b in blocks), strict=True):
            if session.cache.stale(h):
                return JSONResponse(block.line)
        return JSONResponse(None)

    async def get_modules(request: Request):
        path, _ = document(request)
        return JSONResponse(await run_in_threadpool(modules, path.parent))

    async def interrupt(request: Request):
        document(request)[1].interrupt()
        return Response(status_code=204)

    async def restart(request: Request):
        await run_in_threadpool(document(request)[1].restart)
        return Response(status_code=204)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        yield
        for session in sessions.values():  # no worker outlives the server
            await run_in_threadpool(session.restart)

    doc = "/edit/{doc:path}"
    return Starlette(
        routes=[
            Route("/", index),
            Route("/new", new, methods=["POST"]),
            Route(f"{doc}/doc", put_doc, methods=["PUT"]),
            Route(f"{doc}/run", run, methods=["POST"]),
            Route(f"{doc}/complete", assist, methods=["POST"]),
            Route(f"{doc}/signature", assist, methods=["POST"]),
            Route(f"{doc}/modules", get_modules),
            Route(f"{doc}/stale", stale_line, methods=["POST"]),
            Route(f"{doc}/interrupt", interrupt, methods=["POST"]),
            Route(f"{doc}/restart", restart, methods=["POST"]),
            Route(doc, editor),
            Mount("/static", RevalidatedStaticFiles(directory=HERE / "static"), name="static"),
        ],
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]),
            Middleware(TokenMiddleware, token=token),
        ],
        lifespan=lifespan,
    )
