from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # only for the annotation; no runtime import, so item.py can import this module
    from gather.item import Item

# The method ladder: how directly an item's text reflects its source. A DIRECT method retrieved
# the text as-is (a fetch, a read, a transcription); a DERIVED method produced new text from other
# items (an assembly or an inference). The receipt's method records which, so a quote is never
# confused with an inference; this module makes that distinction queryable AND enforced (make_item
# rejects an item whose method contradicts its derivation chain).
DIRECT_METHODS = frozenset({
    "yt-dlp", "auto-caption", "http-get", "file-read", "feed",
    "arxiv-api", "arxiv-api-id", "arxiv-api-search", "pdftotext",
    "api-get", "ocr", "transcribe", "browser-extract", "browser-evidence",
    "discord-api-message",
    # scholarly-graph federation: each provider's paper fetch, and a citation edge (the provider
    # asserted the link; gather records that it did). All DIRECT. See gather.scholar.
    "openalex-api", "semanticscholar-api", "crossref-api", "citation-edge",
})
DERIVED_METHODS = frozenset({"compiled", "synthesized"})

DIRECT = "direct"
DERIVED = "derived"
UNKNOWN = "unknown"


def directness(method: str) -> str:
    """Classify a method as ``direct``, ``derived``, or ``unknown`` (an unregistered label)."""
    if method in DERIVED_METHODS:
        return DERIVED
    if method in DIRECT_METHODS:
        return DIRECT
    return UNKNOWN


def consistent(method: str, has_derived_from: bool) -> bool:
    """True if a method agrees with whether a derivation chain is present: a derived method must
    have inputs, a direct method must not, and an unknown method makes no claim (always True)."""
    rung = directness(method)
    if rung == DERIVED:
        return has_derived_from
    if rung == DIRECT:
        return not has_derived_from
    return True


def is_consistent(item: Item) -> bool:
    """consistent() for a built Item: its method must agree with its derived_from chain."""
    return consistent(item.provenance.method, bool(item.provenance.derived_from))
