"""Witnessable adaptive element tracking.

Scrapling's headline feature is relocating a scraped element after a site's
markup shifts. gather does the same, but emits a re-checkable verdict instead of
a silent best guess: a fingerprint taken now is relocated against a later version
of the page and the result is one of a closed set with a residual, so a reviewer
can see whether the element is the same, merely moved, drifted, or gone.

    MATCH      same path and byte-identical text (residual 0.0)
    RELOCATED  byte-identical text at a different path (the element moved)
    DRIFT      the element was found but its text changed (residual = 1 - sim)
    GONE       no candidate cleared the match floor

This is the accountability layer none of the scraping tools carry: a scrape that
silently returns the wrong element after a redesign is exactly the failure this
verdict makes visible. Pure and deterministic; no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gather.dom import Node
from gather.item import content_hash

VERDICTS = ("MATCH", "RELOCATED", "DRIFT", "GONE")
DEFAULT_FLOOR = 0.35  # minimum blended score for a non-GONE verdict


def _tokens(text: str) -> frozenset[str]:
    return frozenset(text.lower().split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """A re-checkable signature of one element, taken at fetch time. ``text`` is
    bounded so the fingerprint stays small yet the relocation is reproducible:
    another reviewer with the same later page gets the same verdict."""

    tag: str
    node_id: str
    classes: tuple[str, ...]
    path: str
    text_sha256: str
    text_len: int
    text: str = ""  # bounded sample used for similarity scoring

    def as_dict(self) -> dict:
        return {
            "tag": self.tag, "node_id": self.node_id, "classes": list(self.classes),
            "path": self.path, "text_sha256": self.text_sha256,
            "text_len": self.text_len,
        }


def fingerprint(node: Node, *, sample_chars: int = 2000) -> Fingerprint:
    """Take a fingerprint of ``node``. Pure."""
    text = node.text_content()
    return Fingerprint(
        tag=node.tag, node_id=node.node_id, classes=node.classes, path=node.path,
        text_sha256=content_hash(text), text_len=len(text), text=text[:sample_chars],
    )


@dataclass(frozen=True, slots=True)
class Relocation:
    """The witnessed result of relocating a fingerprint against a new tree."""

    verdict: str
    residual: float          # 0.0 == identical content; higher == more changed
    score: float             # blended candidate confidence in [0, 1]
    found_path: str          # path of the chosen node, "" if GONE
    found_text_sha256: str   # content hash of the chosen node's text, "" if GONE
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict, "residual": round(self.residual, 6),
            "score": round(self.score, 6), "found_path": self.found_path,
            "found_text_sha256": self.found_text_sha256, "evidence": self.evidence,
        }


def _score(fp: Fingerprint, node: Node, node_text: str) -> tuple[float, float]:
    """Return ``(blended_score, text_similarity)`` for a candidate node."""
    text_sim = 1.0 if content_hash(node_text) == fp.text_sha256 else _jaccard(
        _tokens(fp.text), _tokens(node_text)
    )
    id_match = 1.0 if fp.node_id and node.node_id == fp.node_id else 0.0
    class_sim = _jaccard(frozenset(fp.classes), frozenset(node.classes))
    path_match = 1.0 if node.path == fp.path else 0.0
    score = 0.55 * text_sim + 0.25 * id_match + 0.12 * class_sim + 0.08 * path_match
    return score, text_sim


def relocate(fp: Fingerprint, new_root: Node, *, floor: float = DEFAULT_FLOOR) -> Relocation:
    """Relocate ``fp`` in ``new_root`` and return a witnessed verdict. Pure.

    Candidates are all same-tag nodes; the best-scoring one is chosen. A
    byte-identical text match is decisive (MATCH or RELOCATED by path); otherwise
    a candidate clearing ``floor`` is a DRIFT and anything below it is GONE."""
    best: Node | None = None
    best_score = -1.0
    best_sim = 0.0
    best_text = ""
    candidates = 0
    for node in new_root.walk():
        if node.tag != fp.tag:
            continue
        candidates += 1
        node_text = node.text_content()
        score, text_sim = _score(fp, node, node_text)
        if score > best_score:
            best, best_score, best_sim, best_text = node, score, text_sim, node_text

    evidence = {"candidates": candidates, "tag": fp.tag, "prev_path": fp.path}
    if best is None or best_score < floor:
        return Relocation("GONE", 1.0, max(best_score, 0.0), "", "", evidence)

    found_hash = content_hash(best_text)
    identical = found_hash == fp.text_sha256
    if identical and best.path == fp.path:
        verdict = "MATCH"
    elif identical:
        verdict = "RELOCATED"
    else:
        verdict = "DRIFT"
    residual = 0.0 if identical else 1.0 - best_sim
    return Relocation(verdict, residual, best_score, best.path, found_hash, evidence)
