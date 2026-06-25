from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def content_hash(text: str) -> str:
    """The sha256 of a piece of content: a receipt's fingerprint. Pure and deterministic."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """An auditable origin receipt for one ingested item.

    Records where the item came from, how, when, and a fingerprint of its content, so a
    later reader can re-hash the item and confirm it is the thing that was obtained,
    unaltered. Composes with provenance-sensorium; self-contained here.

    ``method`` is load-bearing when Gather reaches hard sources: it records not just
    that something was fetched but HOW it was obtained, and crucially whether the
    content was pulled directly or DERIVED. A transcript read from captions, a page
    read through a browser, text OCR'd from a scan, speech transcribed from audio, and
    a fact synthesized from fragments are all valid items, but they are not equally
    direct. The method (for example "yt-dlp", "browser-extract", "ocr", "transcribe",
    "synthesized") keeps that distinction on the record, so a quote is never confused
    with an inference. For derived items, ``ref`` should point at what it was derived
    from. The sha256 fingerprints whatever the content actually is.
    """

    source: str        # the adapter's name, e.g. "video"
    ref: str           # the source-scoped reference: a video id, a url, or what a derived item came from
    method: str        # how it was obtained or derived, e.g. "yt-dlp", "ocr", "transcribe", "synthesized"
    fetched_at: float  # unix timestamp the intake happened
    sha256: str        # content_hash of the item's text


@dataclass(frozen=True, slots=True)
class Item:
    """One ingested unit of research: a transcript, a metadata record, a comment, a paper.

    ``text`` is the content; ``meta`` holds source-specific extras. Every item carries a
    Provenance receipt, so nothing enters the constellation without an origin.
    """

    kind: str          # "transcript" | "metadata" | "comment" | "paper" | ...
    id: str            # source-scoped id
    title: str
    text: str
    provenance: Provenance
    meta: dict[str, Any] = field(default_factory=dict)

    def verify(self) -> bool:
        """Re-hash the content and confirm it still matches the receipt."""
        return content_hash(self.text) == self.provenance.sha256


def make_item(
    *,
    kind: str,
    id: str,
    title: str,
    text: str,
    source: str,
    ref: str,
    method: str,
    fetched_at: float,
    meta: dict[str, Any] | None = None,
) -> Item:
    """Build an Item with its provenance receipt computed from the content."""
    prov = Provenance(source=source, ref=ref, method=method, fetched_at=fetched_at, sha256=content_hash(text))
    return Item(kind=kind, id=id, title=title, text=text, provenance=prov, meta=meta or {})
