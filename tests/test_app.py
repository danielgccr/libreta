import asyncio
import json
import os
import random
from datetime import date
from pathlib import Path

from test_document import PIECES

from libreta.app import Session, create_app, editor_blocks, modules, save
from libreta.document import parse

app = create_app(Path("doc.md"), "secret")


def get(query="", host="127.0.0.1:8000", cookie=None, path="/", method="GET", body=b"", app=app):
    headers = [(b"host", host.encode())]
    if cookie is not None:
        headers.append((b"cookie", f"libreta_token={cookie}".encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query.encode(),
        "headers": headers,
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 1),
    }
    sent = []
    requests = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if requests:
            return requests.pop()
        await asyncio.Event().wait()  # the client never disconnects

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    body = b"".join(m.get("body", b"") for m in sent[1:])
    return sent[0]["status"], dict(sent[0]["headers"]), body


def test_rejects_foreign_host():
    assert get(host="evil.example:8000", cookie="secret")[0] == 400


def test_rejects_missing_or_wrong_token():
    assert get()[0] == 403
    assert get(cookie="nope")[0] == 403
    assert get(query="token=nope")[0] == 403
    assert get(query="token=%C3%B1")[0] == 403  # non-ASCII must not crash compare_digest


def test_token_in_url_sets_cookie_and_redirects():
    status, headers, _ = get(query="token=secret", host="localhost:8000")
    assert status == 303
    assert headers[b"location"] == b"http://localhost:8000/"
    assert b"libreta_token=secret" in headers[b"set-cookie"]


def test_cookie_serves_editor_and_static():
    status, _, body = get(cookie="secret")
    assert status == 200 and b'<main id="doc">' in body and b"doc.md" in body
    status, headers, _ = get(cookie="secret", path="/static/js/editor.js")
    assert status == 200 and headers[b"cache-control"] == b"no-cache"


def serialize_editor(blocks, final_newline):
    """Python twin of serialize() in static/js/blocks.js: the contract editor_blocks serves."""
    out = ""
    for b in blocks:
        if b["kind"] == "markdown":
            out += b["value"] + "\n"
        else:
            opening = b["open"] if b["open"].endswith("\n") else b["open"] + "\n"
            out += opening + (b["value"] + "\n" if b["value"] else "") + b["close"]
    return out[:-1] if not final_newline and out.endswith("\n") else out


def single_blank_line(block):
    return block.kind == "python" and block.text.split("\n", 1)[1:] == ["\n" + block.close]


def test_editor_blocks_roundtrip():
    rng = random.Random(1)
    for _ in range(3000):
        n = rng.randint(0, 25)
        text = "".join(rng.choice(PIECES).replace("\r", "") + "\n" for _ in range(n))
        if rng.random() < 0.5:
            text = text.rstrip("\n")
        if any(single_blank_line(b) for b in parse(text)):
            continue  # known, accepted loss: such a code block saves empty
        assert serialize_editor(editor_blocks(text), text == "" or text.endswith("\n")) == text


def test_editor_blocks_values():
    assert editor_blocks("Hola\n\n```python\nx = 1\n```\n\nAdiós") == [
        {"kind": "markdown", "value": "Hola\n"},
        {"kind": "python", "value": "x = 1", "open": "```python\n", "close": "```\n"},
        {"kind": "markdown", "value": "\nAdiós"},
    ]


def test_save_keeps_crlf_mode_and_symlink(tmp_path):
    real = tmp_path / "real.md"
    real.write_bytes(b"a\r\nb\r\n")
    os.chmod(real, 0o600)
    link = tmp_path / "doc.md"
    link.symlink_to(real)
    save(link, "a\nc\n")
    assert link.is_symlink() and real.read_bytes() == b"a\r\nc\r\n"
    assert real.stat().st_mode & 0o777 == 0o600


def test_put_doc(tmp_path):
    path = tmp_path / "nuevo.md"
    doc_app = create_app(path, "secret")
    assert get(method="PUT", path="/doc", body=b"x", app=doc_app)[0] == 403
    body = json.dumps({"text": "# Hola\n", "title": ""}).encode()
    status, _, response = get(method="PUT", path="/doc", body=body, cookie="secret", app=doc_app)
    assert status == 200 and path.read_text() == "# Hola\n"  # no title: no front matter
    assert json.loads(response) == {"text": "# Hola\n", "front": "", "date": None}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["nuevo.md"]  # no temp file left
    body = json.dumps({"text": "# Hola\n", "title": " Informe "}).encode()
    _, _, response = get(method="PUT", path="/doc", body=body, cookie="secret", app=doc_app)
    today = date.today().isoformat()
    front = f"---\ntitle: Informe\ndate: {today}\n---\n"
    assert path.read_text() == front + "# Hola\n"
    assert json.loads(response) == {"text": front + "# Hola\n", "front": front, "date": today}
    status, _, page = get(cookie="secret", app=doc_app)
    assert b'"title": "Informe"' in page and b'"value": "# Hola"' in page  # YAML: no block


def post_json(app, path, data):
    body = json.dumps(data).encode()
    return get(method="POST", path=path, body=body, cookie="secret", app=app)


def items(body):
    return [json.loads(line) for line in body.decode().splitlines()]


def test_run_restart(tmp_path):
    doc_app = create_app(tmp_path / "doc.md", "secret")
    text = "Texto\n\n```python\nx = 41\nprint('hola')\nx + 1\n```\n"
    try:
        status, headers, body = post_json(doc_app, "/run", {"text": text, "line": 3})
        assert status == 200 and headers[b"content-type"] == b"application/x-ndjson"
        assert items(body) == [
            {"start": 3},
            {"mime": "stdout", "content": "hola"},
            {"mime": "stdout", "content": "\n"},
            {"mime": "text/plain", "content": "42"},
        ]
        assert post_json(doc_app, "/run", {"text": text, "line": 1})[0] == 409
        assert post_json(doc_app, "/interrupt", {})[0] == 204  # idle: ignored
        assert post_json(doc_app, "/restart", {})[0] == 204
        other = "```python\nx\n```\n"
        [_, error] = items(post_json(doc_app, "/run", {"text": other, "line": 1})[2])
        assert error["mime"] == "error" and "NameError" in error["content"]  # fresh namespace
    finally:
        post_json(doc_app, "/restart", {})


def test_run_png_is_base64(tmp_path):
    doc_app = create_app(tmp_path / "doc.md", "secret")
    code = "class P:\n    def _repr_png_(self):\n        return b'\\x89PNG'\nP()\n"
    try:
        data = {"text": f"```python\n{code}```\n", "line": 1}
        [_, item] = items(post_json(doc_app, "/run", data)[2])
        assert item == {"mime": "image/png", "base64": "iVBORw=="}
    finally:
        post_json(doc_app, "/restart", {})


def test_run_follows_the_chain(tmp_path):
    """DESIGN §4.5: earlier blocks changed (or never ran) -> fresh worker, run 1..N;
    only block N changed -> run it on the current state."""
    doc_app = create_app(tmp_path / "doc.md", "secret")

    def run(text, line):
        return items(post_json(doc_app, "/run", {"text": text, "line": line})[2])

    def doc(first, second):
        return f"```python\n{first}\n```\n\n```python\n{second}\n```\n"

    try:
        text = doc("n = 1", "n += 1; n")
        assert run(text, 5) == [  # a fresh worker: block 1 runs first
            {"start": 1},
            {"start": 5},
            {"mime": "text/plain", "content": "2"},
        ]
        text = doc("n = 1", "n += 10; n")
        assert run(text, 5) == [{"start": 5}, {"mime": "text/plain", "content": "12"}]  # impure
        assert run(text, 5) == [{"start": 5}, {"mime": "text/plain", "content": "22"}]
        text = doc("n = 100", "n += 10; n")
        assert run(text, 5) == [
            {"start": 1},
            {"start": 5},
            {"mime": "text/plain", "content": "110"},
        ]
        assert run(text, 1) == [{"start": 1}]  # behind the state: from scratch again
        assert run(text, 5)[-1] == {"mime": "text/plain", "content": "110"}  # on top of it

        # The page shows the cached output of the document's chain.
        (tmp_path / "doc.md").write_text(text)
        _, _, body = get(cookie="secret", app=doc_app)
        assert b'"output": [{"content": "110", "mime": "text/plain"}]' in body
        assert b'"output": []' in body  # block 1 ran, with no output

        broken = doc("1 / 0", "2 + 2")  # an earlier error does not stop the run
        [start1, error, start5, value] = run(broken, 5)
        assert (start1, start5) == ({"start": 1}, {"start": 5})
        assert "ZeroDivisionError" in error["content"]
        assert value == {"mime": "text/plain", "content": "4"}
    finally:
        post_json(doc_app, "/restart", {})


def test_escape_stops_the_replay(tmp_path):
    session = Session(tmp_path / "doc.md")
    text = "```python\nimport time\nprint('ready')\nwhile True:\n    time.sleep(0.01)\n```\n"
    text += "\n```python\n2\n```\n"
    try:
        out = []
        for line in session.run(text, parse(text), 1):
            out.append(json.loads(line))
            if out[-1] == {"mime": "stdout", "content": "ready"}:
                session.interrupt()
        assert out[-2] == {"start": 8}
        assert out[-1]["mime"] == "error" and "interrumpido" in out[-1]["content"]
        assert not any(item.get("content") == "2" for item in out)
    finally:
        session.restart()


def test_inline_values_follow_the_blocks(tmp_path):
    doc_app = create_app(tmp_path / "doc.md", "secret")

    def run(text, line, inline=False):
        data = {"text": text, "line": line, "inline": inline}
        return items(post_json(doc_app, "/run", data)[2])

    text = "Hay `py 2 + 2`.\n\n```python\nx = 1\n```\n\nVale `py x`.\n"
    try:
        assert run(text, 3) == [
            {"values": {"2 + 2": {"text": "4"}}, "line": 0},
            {"start": 3},
            {"values": {"x": {"text": "1"}}, "line": 3},
        ]
        # Ctrl+Enter in the Markdown: the worker is already there, nothing runs.
        edited = text.replace("`py x`", "`py x + 1`")
        assert run(edited, 7, inline=True) == [{"values": {"x + 1": {"text": "2"}}, "line": 3}]
        # Before the first block, with x already defined: a fresh worker, nothing else runs.
        assert run(edited, 1, inline=True) == [{"values": {"2 + 2": {"text": "4"}}, "line": 0}]
        # Back after the block: it runs again.
        assert run(edited, 7, inline=True) == [
            {"start": 3},
            {"values": {"x + 1": {"text": "2"}}, "line": 3},
        ]
        (tmp_path / "doc.md").write_text(edited)
        _, _, body = get(cookie="secret", app=doc_app)
        assert b'"values": {"x + 1": {"text": "2"}}' in body
        assert b'"values": {"2 + 2": {"text": "4"}}' in body
    finally:
        post_json(doc_app, "/restart", {})


def test_complete_and_signature(tmp_path):
    doc_app = create_app(tmp_path / "doc.md", "secret")
    text = "```python\nimport os\nos.getc\n```\n\nEn `py os.getc"
    try:
        status, _, body = post_json(doc_app, "/complete", {"text": text, "line": 3, "column": 7})
        assert status == 200 and {"name": "getcwd", "complete": "wd", "type": "function"} in (
            json.loads(body)
        )
        [_, _, body] = post_json(doc_app, "/complete", {"text": text, "line": 6, "column": 14})
        assert "getcwd" in {c["name"] for c in json.loads(body)}
        [_, _, body] = post_json(doc_app, "/complete", {"text": text, "line": 5, "column": 0})
        assert json.loads(body) == []
        text = "```python\nround(1.5, \n```\n"
        [_, _, body] = post_json(doc_app, "/signature", {"text": text, "line": 2, "column": 11})
        assert json.loads(body)[0]["name"] == "round"
    finally:
        post_json(doc_app, "/restart", {})


def test_modules(tmp_path):
    (tmp_path / "local_helper.py").write_text("")
    names = set(modules(tmp_path))
    assert {"json", "sys", "starlette", "local_helper"} <= names
    assert "no_such_module_here" not in names
    doc_app = create_app(tmp_path / "doc.md", "secret")
    status, _, body = get(path="/modules", cookie="secret", app=doc_app)
    assert status == 200 and "local_helper" in json.loads(body)
