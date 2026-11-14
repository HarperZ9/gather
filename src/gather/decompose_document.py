"""Content tables for text documents: facts, headings and reference-like entities.

Plain text, Markdown and HTML are read with the standard library. HTML is recognised from its
first bytes (a doctype or an ``<html`` tag) and read with ``html.parser``: script and style text
is dropped. Headings are Markdown ``#`` lines or HTML ``h1`` to ``h6``. References are the entity
rules from ``gather.saves_entities`` (addresses, DOIs, arXiv ids, dates and the rest), so they
are regular expressions and will miss and over-match. A file that is not UTF-8 text gives no
tables.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from gather.saves_entities import extract_entities

MAX_BYTES = 16 << 20
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_HTML = re.compile(rb"\s*(?:<!doctype html|<html)", re.I)
_LEVELS = {f"h{n}": n for n in range(1, 7)}


def is_pdf(path: str) -> bool:
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


class _Page(HTMLParser):
    """Collects visible text and headings from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.headings: list[dict] = []
        self._skip = 0
        self._open: list | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _LEVELS:
            self._open = [_LEVELS[tag], []]

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _LEVELS and self._open:
            self.headings.append({"level": self._open[0], "text": " ".join("".join(self._open[1]).split())})
            self._open = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._open:
            self._open[1].append(data)


def _read_text(path: str) -> str | None:
    with open(path, "rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or b"\x00" in raw or not raw:
        return None
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return None


def _parse(text: str) -> tuple[str, str, list[dict]]:
    """(form, visible text, headings) for HTML or for plain text and Markdown."""
    if _HTML.match(text[:1024].encode("utf-8")):
        page = _Page()
        page.feed(text)
        page.close()
        return "html", "".join(page.text), [{"order": i, **h} for i, h in enumerate(page.headings, 1)]
    headings: list[dict] = []
    for line in text.split("\n"):
        match = _HEADING.match(line)
        if match:
            headings.append({"order": len(headings) + 1, "level": len(match.group(1)), "text": match.group(2)})
    return "text", text, headings


def document_tables(path: str) -> dict:
    """Tables keyed by file name, or an empty dict when the file is not UTF-8 text."""
    text = _read_text(path)
    if text is None:
        return {}
    form, visible, headings = _parse(text)
    references = extract_entities(visible)
    facts = [{"field": "form", "value": form}, {"field": "text_length", "value": len(visible)},
             {"field": "lines", "value": visible.count("\n") + 1}, {"field": "headings", "value": len(headings)},
             {"field": "references", "value": len(references)}]
    return {"document_facts.csv": (("field", "value"), facts),
            "document_headings.csv": (("order", "level", "text"), headings),
            "document_references.csv": (("type", "value", "normalized", "count"), references)}
