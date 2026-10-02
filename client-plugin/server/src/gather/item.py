from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from gather.method import consistent, directness


def content_hash(text: str) -> str:
    """The sha256 of a piece of content: a receipt's fingerprint. Pure and deterministic."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """An auditable origin receipt for one ingested item.

    Records where the item came from, how, when, and a fingerprint of its content, so a
    later reader can re-hash the item and confirm it is the thing that was obtained,
    unaltered.

    ``method`` is load-bearing when Gather reaches hard sources: it records not just
    that something was fetched but HOW it was obtained, and crucially whether the
    content was pulled directly or DERIVED. A transcript read from captions, a page
    read through a browser, text OCR'd from a scan, speech transcribed from audio, and
    a fact synthesized from fragments are all valid items, but they are not equally
    direct. The method (for example "yt-dlp", "browser-extract", "ocr", "transcribe",
    "synthesized") keeps that distinction on the record, so a quote is never confused
    with an inference.

    ``sha256`` always fingerprints the item's own ``text``. For a directly fetched item
    that text IS the source content, so the hash witnesses the source. For a DERIVED item
    (``method="synthesized"`` or ``"compiled"``) the text is the inference or assembly, so
    the hash witnesses that, not its inputs; ``derived_from`` then carries the content hash
    of each input, a re-checkable pointer into the corpus, so the chain back to sources
    stays verifiable and a derived item is never mistaken for a direct one. Composes with
    provenance-sensorium.
    """

    source: str        # the adapter's name, e.g. "video"
    ref: str           # the source-scoped reference: a video id, a url, or what a derived item came from
    method: str        # how it was obtained or derived, e.g. "yt-dlp", "ocr", "transcribe", "synthesized"
    fetched_at: float  # unix timestamp the intake happened
    sha256: str        # content_hash of the item's text (the source content, or the inference itself if derived)
    derived_from: tuple[str, ...] = ()  # content hashes of the inputs an inference was built from; empty if fetched


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
    derived_from: tuple[str, ...] = (),
    meta: dict[str, Any] | None = None,
) -> Item:
    """Build an Item with its provenance receipt computed from the content.

    For a derived item, pass ``derived_from`` with the inputs the inference was built from;
    the receipt's sha256 still fingerprints this item's own ``text`` (the inference). The method
    ladder is enforced here: a derived method (compiled/synthesized) must carry ``derived_from``
    and a direct method (a fetch/read) must not, so a fetched item cannot be dressed up as an
    inference or vice versa. An unregistered method makes no claim and is allowed either way.
    """
    derived_from = tuple(derived_from)
    if not consistent(method, bool(derived_from)):
        raise ValueError(
            f"method {method!r} is {directness(method)} but derived_from is "
            f"{'set' if derived_from else 'empty'}: a direct fetch carries no inputs and a "
            f"derived item must record them"
        )
    prov = Provenance(
        source=source, ref=ref, method=method, fetched_at=fetched_at,
        sha256=content_hash(text), derived_from=derived_from,
    )
    return Item(kind=kind, id=id, title=title, text=text, provenance=prov, meta=meta or {})
