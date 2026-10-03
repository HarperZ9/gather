"""A code check on every citation in a report. Pure: no network, no model.

A report cites an excerpt by quoting it and naming its number: ``"the exact words" [2]``. For
each citation the check decides, by string comparison alone:

- ``verified``: the quoted span appears in excerpt 2 (after Unicode, quote-mark, dash and
  whitespace normalisation, and case folding);
- ``not-in-source``: excerpt 2 exists and does not contain the span;
- ``unknown-source``: there is no excerpt 2;
- ``too-short``: the quote has fewer than ``MIN_QUOTE_WORDS`` words, so a match would prove
  little; it is not counted as verified;
- ``unchecked``: a bracketed number with no quote before it, so there is nothing to compare.

Sentences with no citation at all are listed as uncited. Nothing is hidden: every citation and
every uncited sentence is in the result. Precision is verified citations over all citations.

What this does not check: whether the sentence around a verified quote says what the excerpt
means. A quote can be exact and the claim around it can still stretch it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CHECK_SCHEMA = "gather.citation-check/1"
MIN_QUOTE_WORDS = 4
STATUSES = ("verified", "not-in-source", "unknown-source", "too-short", "unchecked")

_MARKS = str.maketrans({"“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
                        "‘": "'", "’": "'", "–": "-", "—": "-", "−": "-",
                        " ": " "})
# a double-quoted span, optional space, then [n]
_QUOTE_CITE = re.compile(r'"([^"]{1,2000})"\s*\[(\d{1,4})\]')
_BARE_CITE = re.compile(r"\[(\d{1,4})\]")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d{1,3}[.)])\s+")
_SENTENCE = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=["(\[A-Z0-9])')


def normalize(text: str) -> str:
    """NFKC, straight quote marks and hyphens, collapsed whitespace, case folded."""
    text = unicodedata.normalize("NFKC", text).translate(_MARKS)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strip_edges(quote: str) -> str:
    return normalize(quote).strip(" .,;:!?'")


@dataclass(frozen=True, slots=True)
class Citation:
    sentence: int
    source: int
    quote: str | None
    status: str

    def to_dict(self) -> dict:
        return {"sentence": self.sentence, "source": self.source, "quote": self.quote, "status": self.status}


def _split_line(line: str) -> list[str]:
    """Split one line at sentence ends that fall outside a double-quoted span."""
    parts, start = [], 0
    for m in _SENTENCE.finditer(line):
        if line[:m.start()].count('"') % 2 == 0:
            parts.append(line[start:m.start() + len(m.group(0).rstrip())].strip())
            start = m.end()
    parts.append(line[start:].strip())
    return [p for p in parts if p]


def sentences(report: str) -> list[str]:
    """The report's sentences: lines split at sentence ends outside quotes, list markers removed,
    headings and blank lines dropped."""
    out: list[str] = []
    for raw in report.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.extend(_split_line(_LIST_MARK.sub("", line.translate(_MARKS))))
    return out


def _status(quote: str, source: int, excerpts: list[str]) -> str:
    if not 1 <= source <= len(excerpts):
        return "unknown-source"
    span = _strip_edges(quote)
    if len(span.split()) < MIN_QUOTE_WORDS:
        return "too-short"
    return "verified" if span in normalize(excerpts[source - 1]) else "not-in-source"


def _sentence_citations(n: int, sentence: str, excerpts: list[str]) -> list[Citation]:
    found = [Citation(n, int(m.group(2)), m.group(1), _status(m.group(1), int(m.group(2)), excerpts))
             for m in _QUOTE_CITE.finditer(sentence.translate(_MARKS))]
    bare_text = _QUOTE_CITE.sub("", sentence.translate(_MARKS))
    found += [Citation(n, int(m.group(1)), None, "unchecked") for m in _BARE_CITE.finditer(bare_text)]
    return found


def check_report(report: str, excerpts: list[str]) -> dict:
    """Check every citation in ``report`` against ``excerpts`` (excerpt 1 is ``excerpts[0]``)."""
    cites: list[Citation] = []
    uncited: list[str] = []
    for n, sentence in enumerate(sentences(report)):
        found = _sentence_citations(n, sentence, excerpts)
        cites.extend(found)
        if not found:
            uncited.append(sentence)
    counts = {s: sum(1 for c in cites if c.status == s) for s in STATUSES}
    total = len(cites)
    return {
        "schema": CHECK_SCHEMA, "excerpts": len(excerpts), "citations": [c.to_dict() for c in cites],
        "counts": counts, "total": total,
        "precision": round(counts["verified"] / total, 4) if total else None,
        "uncited_sentences": uncited,
        "does_not_prove": "that the claim around a verified quote matches the excerpt's meaning",
    }
