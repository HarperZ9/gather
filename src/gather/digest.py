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
    hash, source, ref, method, derived_from), plus the ``availability`` rung when a receipt
    carries one (gather.availability); an item's ``meta`` is source-specific extra and is
    deliberately not carried in the digest, so it is neither shown nor sealed here.
    """

    receipts: tuple[dict, ...]
    seal: str

    def to_json(self) -> str:
        return json.dumps({"receipts": list(self.receipts), "seal": self.seal}, indent=2, ensure_ascii=False)


def _seal(receipts: list[dict]) -> str:
    """A deterministic fingerprint over the receipts, recomputable from the record.

    The receipts are sorted, so the seal depends on what was gathered, not on the order it
    happened to arrive. Each receipt is canonicalized as a named-key JSON object (not a
    positional array), so the mapping from receipt to bytes is unambiguous and no permutation
    of field values can collide. The seal folds in every field the digest carries: content
    hash, kind, id, title, source, ref, method, and derived_from. So relabelling how an item
    was obtained (passing a synthesis off as a direct fetch), rewriting a title, or changing
    what an inference was built from all break the seal exactly as tampering with the content
    does. ``derived_from`` is kept in its original order, so reordering an inference's inputs
    is itself detected. A receipt carrying an ``availability`` rung has it folded in too, so
    an availability claim cannot be edited, grafted on, or stripped off after witnessing; a
    receipt without one seals byte-identically to before the rung existed (legacy compatible).
    """
    objs = []
    for r in receipts:
        o = {
            "sha256": r["sha256"], "kind": r["kind"], "id": r["id"], "title": r["title"],
            "source": r["source"], "ref": r["ref"], "method": r["method"],
            "derived_from": list(r.get("derived_from") or []),
        }
        if r.get("availability") is not None:
            o["availability"] = r["availability"]
        objs.append(o)
    objs.sort(key=lambda d: json.dumps(d, sort_keys=True, ensure_ascii=False))
    canon = json.dumps(objs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_FIELDS = ("kind", "id", "title", "source", "ref", "method", "sha256")

_HEX = set("0123456789abcdef")


def _check_rung(av: object) -> dict:
    """Shape-check an availability rung before it is sealed: exactly a status string, a numeric
    checked_at, and a sha256 binding (the content hash the claim is bound to, or "" when nothing
    was observed). Sealing garbage would launder it, so a malformed rung raises a clear
    ValueError here; what a status MEANS is gather.availability's business, not the seal's."""
    if not isinstance(av, dict):
        raise ValueError(f"availability rung is not an object: {str(av)[:48]!r}")
    status, checked_at, sha = av.get("status"), av.get("checked_at"), av.get("sha256")
    if not isinstance(status, str) or not status:
        raise ValueError("availability rung needs a non-empty status string")
    if isinstance(checked_at, bool) or not isinstance(checked_at, (int, float)):
        raise ValueError("availability rung needs a numeric checked_at")
    if not isinstance(sha, str) or (sha and (len(sha) != 64 or any(c not in _HEX for c in sha))):
        raise ValueError("availability rung sha256 must be a content hash or empty")
    return {"status": status, "checked_at": checked_at, "sha256": sha}


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
    ValueError (rows can come from disk, so the failure must be diagnosable, not a bare KeyError).
    An ``availability`` rung, when present, is shape-checked and carried into the sealed receipt
    (see gather.availability); a receipt without one seals exactly as before rungs existed."""
    clean = []
    for r in receipts:
        missing = [k for k in _FIELDS if k not in r]
        if missing:
            raise ValueError(f"receipt missing required field(s) {missing}")
        row = {**{k: r[k] for k in _FIELDS}, "derived_from": list(r.get("derived_from") or [])}
        if r.get("availability") is not None:
            row["availability"] = _check_rung(r["availability"])
        clean.append(row)
    return Digest(receipts=tuple(clean), seal=_seal(clean))


def verify_digest(d: Digest) -> bool:
    """Recompute the seal from the receipts and confirm it matches."""
    return _seal(list(d.receipts)) == d.seal
