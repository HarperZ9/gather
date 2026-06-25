from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from gather.item import Item


@dataclass(frozen=True, slots=True)
class Digest:
    """A compact, provenance-stamped record of a gather run, witnessed and re-checkable.

    Lists every ingested item's origin receipt and folds them into one ``seal``. index,
    refine, and the crucible consume this; the seal lets a reader confirm the digest was
    not altered after the fact, the same proof-over-trust the rest of the constellation
    runs on.
    """

    receipts: tuple[dict, ...]
    seal: str

    def to_json(self) -> str:
        return json.dumps({"receipts": list(self.receipts), "seal": self.seal}, indent=2, ensure_ascii=False)


def _seal(receipts: list[dict]) -> str:
    """A deterministic fingerprint over the receipts, recomputable from the record.

    Order-independent (the receipts are sorted by their content fingerprint), so the
    seal depends on what was gathered, not on the order it happened to arrive.
    """
    canon = json.dumps(sorted((r["sha256"], r["kind"], r["id"]) for r in receipts), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def digest(items: list[Item]) -> Digest:
    """Fold a set of ingested items into a witnessed digest."""
    receipts = [
        {
            "kind": i.kind, "id": i.id, "title": i.title,
            "source": i.provenance.source, "ref": i.provenance.ref,
            "method": i.provenance.method, "sha256": i.provenance.sha256,
        }
        for i in items
    ]
    return Digest(receipts=tuple(receipts), seal=_seal(receipts))


def verify_digest(d: Digest) -> bool:
    """Recompute the seal from the receipts and confirm it matches."""
    return _seal(list(d.receipts)) == d.seal
