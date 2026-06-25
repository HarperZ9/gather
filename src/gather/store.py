from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from gather.digest import Digest, digest_of_receipts
from gather.item import Item, Provenance, content_hash

MATCH = "MATCH"        # the stored body still hashes to its receipt
MISSING = "MISSING"    # the receipt points at a body that is not in the store
CORRUPT = "CORRUPT"    # the stored body no longer hashes to its receipt

_HEX = set("0123456789abcdef")


def _check_sha(sha: str) -> str:
    """A content hash is exactly 64 lowercase hex chars. Reject anything else BEFORE it is used
    to build a filesystem path, so a tampered catalog cannot drive a path-traversal read."""
    if len(sha) != 64 or any(c not in _HEX for c in sha):
        raise ValueError(f"not a valid content hash: {sha[:48]!r}")
    return sha


class Corpus:
    """A content-addressed, re-verifiable store of gathered items.

    Layout under ``root``: ``objects/ab/cdef...`` holds each item's body keyed by the sha256 of
    its content, so identical content is stored once (the natural dedup); ``catalog.jsonl`` is an
    append log of one row per DISTINCT receipt. Crucially the dedup is at the body level only:
    two different items with byte-identical text (different source, ref, or method) keep BOTH
    receipts and share one body, so no provenance is ever dropped. Re-adding an item whose whole
    receipt already exists is the no-op that is deduped.

    Because a body lives at the address of its own hash, the store is self-verifying: ``verify``
    re-hashes every stored body and reports MATCH, MISSING, or CORRUPT, making the digest's
    proof-over-trust durable over a growing corpus.

    Efficiency and durability: content-addressing dedups bodies; bodies are read one at a time
    (``verify`` never holds them all in memory), though the small receipt rows are collected to
    compute a seal. With ``fsync`` (the default) each body and the catalog are flushed to disk so
    the word "durable" is earned; pass ``fsync=False`` for a faster bulk load that trades that
    guarantee. ``add`` scans the existing catalog once to dedup against it, so it assumes a single
    writer at a time.
    """

    def __init__(self, root: str, *, fsync: bool = True) -> None:
        self._root = root
        self._objects = os.path.join(root, "objects")
        self._catalog = os.path.join(root, "catalog.jsonl")
        self._runs = os.path.join(root, "runs.jsonl")
        self._fsync = fsync

    def _object_path(self, sha: str) -> str:
        v = _check_sha(sha)  # validate once, then build both path parts from the validated value
        return os.path.join(self._objects, v[:2], v[2:])

    def _write_object(self, text: str) -> tuple[str, bool]:
        """Write a body addressed by its hash. Returns ``(sha, is_new)``; an existing body is a
        no-op (dedup). Written to a temp file then renamed, so a body is never half-present."""
        sha = content_hash(text)
        path = self._object_path(sha)
        if os.path.exists(path):
            return sha, False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
        return sha, True

    @staticmethod
    def _key(row: dict) -> tuple:
        """The identity of a receipt: its sealed fields (not fetched_at or meta). Two rows with
        the same key are the same item, so re-adding one is a no-op."""
        return (row["kind"], row["id"], row["title"], row["source"], row["ref"],
                row["method"], row["sha256"], tuple(row.get("derived_from") or []))

    def add(self, items: list[Item]) -> dict[str, int]:
        """Add items. Returns counts ``{added, deduped, total}``.

        Every distinct receipt is appended (so provenance is never dropped); a body already
        present is reused, and an item whose whole receipt already exists is deduped. ``meta`` must
        be JSON-serializable. Each call scans the existing catalog once to dedup against it, so the
        cost is O(catalog size) per call (O(K x N) over K incremental adds); for a bulk load, batch
        items into one ``add``. Memory stays flat (the catalog streams). Single-writer.
        """
        os.makedirs(self._root, exist_ok=True)
        seen = {self._key(r) for r in self.rows()}
        added = deduped = 0
        with open(self._catalog, "a", encoding="utf-8") as cat:
            for it in items:
                self._write_object(it.text)  # dedups the body
                row = self._row(it)
                key = self._key(row)
                if key in seen:
                    deduped += 1
                    continue
                seen.add(key)
                try:
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                except TypeError as exc:
                    raise ValueError(f"item {it.id!r} has non-JSON-serializable meta: {exc}") from exc
                cat.write(line + "\n")
                added += 1
            cat.flush()
            if self._fsync:
                os.fsync(cat.fileno())
        if self._fsync:
            self._fsync_dir(self._root)
        return {"added": added, "deduped": deduped, "total": len(items)}

    @staticmethod
    def _fsync_dir(path: str) -> None:
        if os.name != "posix":  # opening a directory for fsync is POSIX-only
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _row(it: Item) -> dict[str, Any]:
        p = it.provenance
        return {
            "kind": it.kind, "id": it.id, "title": it.title,
            "source": p.source, "ref": p.ref, "method": p.method,
            "sha256": p.sha256, "derived_from": list(p.derived_from),
            "fetched_at": p.fetched_at, "meta": it.meta,
        }

    @staticmethod
    def _stream_jsonl(path: str, what: str) -> Iterator[dict]:
        """Stream a JSONL file one row at a time. A malformed line raises a located ValueError
        rather than a silent skip (an accountable store surfaces corruption, it does not hide it)."""
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"corpus {what} line {n} is not valid JSON: {exc}") from exc

    def rows(self) -> Iterator[dict]:
        """Stream the catalog rows (one receipt per distinct item), one at a time."""
        yield from self._stream_jsonl(self._catalog, "catalog")

    def add_record(self, record: dict) -> None:
        """Append one witnessed run record to the durable run history (runs.jsonl)."""
        os.makedirs(self._root, exist_ok=True)
        with open(self._runs, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())

    def runs(self) -> Iterator[dict]:
        """Stream the run history: one witnessed RunRecord (as a dict) per gather session."""
        yield from self._stream_jsonl(self._runs, "runs")

    def load_item(self, row: dict) -> Item:
        """Reconstruct a full Item (body read from its object) from a catalog row. Note JSON's
        type limits: meta round-trips as JSON (tuples become lists); derived_from is restored as
        a tuple. The reconstructed item re-verifies, since the body hashes to its receipt."""
        text = self.read_text(row["sha256"])
        prov = Provenance(
            source=row["source"], ref=row["ref"], method=row["method"],
            fetched_at=row["fetched_at"], sha256=row["sha256"],
            derived_from=tuple(row.get("derived_from") or []),
        )
        return Item(kind=row["kind"], id=row["id"], title=row["title"], text=text,
                    provenance=prov, meta=row.get("meta") or {})

    def read_text(self, sha256: str) -> str:
        with open(self._object_path(sha256), encoding="utf-8") as f:
            return f.read()

    def verify(self) -> list[dict]:
        """Re-hash every stored body against its receipt. Returns one row per catalog entry with a
        ``status`` of MATCH, MISSING, or CORRUPT. Reads bodies one at a time (never all at once)."""
        results = []
        for row in self.rows():
            sha = row["sha256"]
            try:
                path = self._object_path(sha)
            except ValueError:
                results.append({"id": row.get("id", ""), "sha256": sha, "status": CORRUPT})
                continue
            if not os.path.exists(path):
                status = MISSING
            else:
                status = MATCH if content_hash(self.read_text(sha)) == sha else CORRUPT
            results.append({"id": row["id"], "sha256": sha, "status": status})
        return results

    def digest(self) -> Digest:
        """Fold the whole corpus catalog into one witnessed digest, from the rows alone. Equals a
        live ``digest(items)`` when the corpus holds exactly those distinct items."""
        return digest_of_receipts(list(self.rows()))
