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


class Corpus:
    """A durable, content-addressed store of gathered items, re-verifiable against its receipts.

    Layout under ``root``: ``objects/ab/cdef...`` holds each item's body keyed by the sha256 of
    its content (so identical content is stored once, the natural dedup), and ``catalog.jsonl``
    is an append log of one receipt row per distinct item. Because a body lives at the address
    of its own hash, the store is self-verifying: ``verify`` re-hashes every stored body and
    reports MATCH, MISSING, or CORRUPT, the same proof-over-trust the digest gives a single run,
    made durable over a growing corpus.

    Efficiency is deliberate: content-addressing dedups bodies, the catalog is read as a stream
    (one row at a time, never the whole corpus in memory), and bodies are written once and
    addressed by hash thereafter.
    """

    def __init__(self, root: str) -> None:
        self._root = root
        self._objects = os.path.join(root, "objects")
        self._catalog = os.path.join(root, "catalog.jsonl")

    def _object_path(self, sha: str) -> str:
        return os.path.join(self._objects, sha[:2], sha[2:])

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
        os.replace(tmp, path)
        return sha, True

    def add(self, items: list[Item]) -> dict[str, int]:
        """Add items to the corpus. Returns counts ``{added, deduped, total}``.

        Each distinct content is stored once; re-adding content already present is a deduped
        no-op that keeps the first ingestion's receipt (so the corpus holds each distinct body
        once). Two different items with byte-identical text therefore resolve to the first's
        provenance; that is the documented trade for content-addressed dedup.
        """
        added = deduped = 0
        os.makedirs(self._root, exist_ok=True)
        with open(self._catalog, "a", encoding="utf-8") as cat:
            for it in items:
                _sha, is_new = self._write_object(it.text)
                if not is_new:
                    deduped += 1
                    continue
                cat.write(json.dumps(self._row(it), ensure_ascii=False, sort_keys=True) + "\n")
                added += 1
        return {"added": added, "deduped": deduped, "total": len(items)}

    @staticmethod
    def _row(it: Item) -> dict[str, Any]:
        p = it.provenance
        return {
            "kind": it.kind, "id": it.id, "title": it.title,
            "source": p.source, "ref": p.ref, "method": p.method,
            "sha256": p.sha256, "derived_from": list(p.derived_from),
            "fetched_at": p.fetched_at, "meta": it.meta,
        }

    def rows(self) -> Iterator[dict]:
        """Stream the catalog rows, one at a time. Empty if the corpus has no catalog yet."""
        if not os.path.exists(self._catalog):
            return
        with open(self._catalog, encoding="utf-8") as cat:
            for line in cat:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def load_item(self, row: dict) -> Item:
        """Reconstruct a full Item (body read from its object) from a catalog row."""
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
        """Re-hash every stored body against its receipt. Returns one row per catalog entry with
        a ``status`` of MATCH, MISSING, or CORRUPT. Streams; does not hold the corpus in memory."""
        results = []
        for row in self.rows():
            sha = row["sha256"]
            path = self._object_path(sha)
            if not os.path.exists(path):
                status = MISSING
            else:
                status = MATCH if content_hash(self.read_text(sha)) == sha else CORRUPT
            results.append({"id": row["id"], "sha256": sha, "status": status})
        return results

    def digest(self) -> Digest:
        """Fold the whole corpus catalog into one witnessed digest, from the rows alone."""
        return digest_of_receipts(list(self.rows()))
