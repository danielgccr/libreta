"""Block outputs on disk, keyed by chained hashes (DESIGN §5).

``h_i = sha256(h_{i-1} + code_i)``: changing a block invalidates it and every block after it.
Each block's outputs are ``<hash>.json`` in ``.libreta/<document name>/`` next to the
document; figures go to files of their own, ``<hash>-<n>.<ext>``, for the export to link.
The values of the inline `py` expressions in the Markdown after the block are
``<hash>-values.json``; those before the first block go under GENESIS.
"""

import base64
import hashlib
import json
import mimetypes
from collections.abc import Iterable
from itertools import accumulate
from pathlib import Path

GENESIS = hashlib.sha256(b"").hexdigest()  # the chain before the first block: empty namespace


def chain(codes: Iterable[str]) -> list[str]:
    """The chained hash of each Python block, given their code in document order."""
    return list(accumulate(codes, _link, initial=GENESIS))[1:]


def _link(h: str, code: str) -> str:
    return hashlib.sha256((h + code).encode()).hexdigest()


def to_json(mime: str, content: str | bytes) -> dict:
    """An output item as the client gets it: ``{mime, content}`` or ``{mime, base64}``."""
    if isinstance(content, bytes):
        return {"mime": mime, "base64": base64.b64encode(content).decode()}
    return {"mime": mime, "content": content}


class Cache:
    def __init__(self, document: Path):
        self.dir = document.parent / ".libreta" / document.name

    def load(self, h: str) -> list[dict] | None:
        """The block's outputs as client items, or None if there is no valid entry."""
        try:
            record = json.loads((self.dir / f"{h}.json").read_text(encoding="utf-8"))
            for item in record:
                if "file" in item:
                    data = (self.dir / item.pop("file")).read_bytes()
                    item["base64"] = base64.b64encode(data).decode()
            return record
        except (OSError, ValueError):  # missing, or half written when a run was killed
            return None

    def save(self, h: str, items: list[tuple[str, str | bytes]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob(f"{h}*"):
            old.unlink()
        record = []
        for n, (mime, content) in enumerate(items):
            if mime.startswith("image/"):
                name = f"{h}-{n}{mimetypes.guess_extension(mime) or ''}"
                data = content.encode() if isinstance(content, str) else content
                (self.dir / name).write_bytes(data)
                record.append({"mime": mime, "file": name})
            else:
                record.append(to_json(mime, content))
        # Written last: a readable .json means its figures are all there.
        (self.dir / f"{h}.json").write_text(json.dumps(record), encoding="utf-8")

    def load_values(self, h: str) -> dict | None:
        try:
            return json.loads((self.dir / f"{h}-values.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save_values(self, h: str, values: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{h}-values.json").write_text(json.dumps(values), encoding="utf-8")

    def prune(self, keep: set[str]) -> None:
        """Delete every entry whose hash is not in `keep` (the document's current chain)."""
        if self.dir.is_dir():
            for file in self.dir.iterdir():
                if file.name[:64] not in keep:
                    file.unlink()
