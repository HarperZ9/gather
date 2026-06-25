from __future__ import annotations

from gather.item import Item

# The method ladder: how directly an item's text reflects its source. A DIRECT method retrieved
# the text as-is (a fetch, a read, a transcription); a DERIVED method produced new text from other
# items (an assembly or an inference). The receipt's method records which, so a quote is never
# confused with an inference; this module makes that distinction queryable and checkable.
DIRECT_METHODS = frozenset({
    "yt-dlp", "auto-caption", "http-get", "file-read", "feed",
    "arxiv-api", "arxiv-api-id", "arxiv-api-search", "pdftotext",
    "api-get", "ocr", "transcribe", "browser-extract",
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


def is_consistent(item: Item) -> bool:
    """True if an item's method agrees with its derivation chain: a derived item must carry
    ``derived_from`` and a direct one must not. An unknown method makes no claim (returns True),
    so a new adapter's label is not rejected, only un-classified."""
    rung = directness(item.provenance.method)
    has_inputs = bool(item.provenance.derived_from)
    if rung == DERIVED:
        return has_inputs
    if rung == DIRECT:
        return not has_inputs
    return True
