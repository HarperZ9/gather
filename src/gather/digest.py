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
    runs on. The seal covers each receipt's identity, title, and full provenance (content
    hash, source, ref, method, derived_from); an item's ``meta`` is source-specific extra
    and is deliberately not carried in the digest, so it is neither shown nor sealed here.
    """

    receipts: tuple[dict, ...]
    seal: str

    def to_json(self) -> str:
        return json.dumps({"receipts": list(self.receipts), "seal": self.seal}, indent=2, ensure_ascii=False)


def _seal(receipts: list[dict]) -> str:
    """A deterministic fingerprint over the receipts, recomputable from the record.

    The receipts are sorted, so the seal depends on what was gathered, not on the order it
    happened to arrive. Within each receipt the seal folds in every field the digest
    carries: content hash, kind, id, title, source, ref, method, and derived_from. So
    relabelling how an item was obtained (passing a synthesis off as a direct fetch),
    rewriting a title, or changing what an inference was built from all break the seal
    exactly as tampering with the content does. ``derived_from`` is kept in its original
    order, not sorted, so reordering the inputs of an inference is itself detected.
    """
    canon = json.dumps(
        sorted(
            [r["sha256"], r["kind"], r["id"], r["title"], r["source"], r["ref"], r["method"],
             list(r.get("derived_from") or [])]
            for r in receipts
        ),
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_FIELDS = ("kind", "id", "title", "source", "ref", "method", "sha256")


def _receipt(i: Item) -> dict:
    return {
        "kind": i.kind, "id": i.id, "title": i.title,
        "source": i.provenance.source, "ref": i.provenance.ref,
        "method": i.provenance.method, "sha256": i.provenance.sha256,
        "derived_from": list(i.provenance.derived_from),
    }


def digest(items: list[Item]) -> Digest:
    """Fold a set of ingested items into a witnessed digest."""
    return digest_of_receipts([_receipt(i) for i in items])


def digest_of_receipts(receipts: list[dict]) -> Digest:
    """Fold receipt dicts (e.g. stored catalog rows) into a witnessed digest, without needing
    the item bodies. Each input must carry the receipt fields; extra keys (fetched_at, meta)
    are ignored, and derived_from defaults to empty. A row missing a field raises a clear
    ValueError (rows can come from disk, so the failure must be diagnosable, not a bare KeyError)."""
    clean = []
    for r in receipts:
        missing = [k for k in _FIELDS if k not in r]
        if missing:
            raise ValueError(f"receipt missing required field(s) {missing}")
        clean.append({**{k: r[k] for k in _FIELDS}, "derived_from": list(r.get("derived_from") or [])})
    return Digest(receipts=tuple(clean), seal=_seal(clean))


def verify_digest(d: Digest) -> bool:
    """Recompute the seal from the receipts and confirm it matches."""
    return _seal(list(d.receipts)) == d.seal
