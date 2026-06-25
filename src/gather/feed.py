from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from gather.item import Item, make_item
from gather.net import http_get
from gather.web import text_from_html


def _local(tag: str) -> str:
    """The local name of a possibly namespaced XML tag (Atom namespaces it, RSS does not)."""
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element, names: set[str]) -> str:
    for child in parent:
        if _local(child.tag) in names:
            return (child.text or "").strip()
    return ""


def _entry_link(entry: ET.Element) -> str:
    """The best link for an entry, by explicit precedence: Atom alternate href, then an RSS
    text link, then any other href. Order within a rel keeps the first seen."""
    by_rel: dict[str, str] = {}
    text_link = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if href:
            by_rel.setdefault(child.get("rel", "alternate"), href)
        elif child.text and child.text.strip():
            text_link = text_link or child.text.strip()
    return by_rel.get("alternate") or text_link or next(iter(by_rel.values()), "")


def _entry_body(entry: ET.Element) -> str:
    """The entry's text body. Atom content/summary declaring HTML (or xhtml) is run through
    the HTML text extractor; an RSS description carries no type signal and is left as the feed
    provided it (stripping untyped text would risk mangling plain-text or math content)."""
    for child in entry:
        if _local(child.tag) not in ("description", "summary", "content"):
            continue
        raw = "".join(child.itertext()).strip()
        if not raw:
            continue
        if "html" in (child.get("type") or "").lower():
            return text_from_html(raw)
        return raw
    return ""


def parse_feed(xml: str | bytes, url: str, *, fetched_at: float, method: str = "feed") -> list[Item]:
    """Parse an RSS or Atom feed into one Item per entry. Pure: no network.

    Handles RSS 2.0 (``channel/item``), RSS 1.0/RDF (``item`` as a direct child of the root),
    and Atom (``feed/entry``) by selecting item/entry elements that are direct children of the
    root or of a ``channel``, never a whole-tree walk (so an ``entry`` nested inside an Atom
    ``source`` is not mistaken for a post). Each entry becomes a "feed-entry" Item: the link
    (or guid/id) is the ref, the description/summary/content is the text. Pass bytes when the
    feed has an XML encoding declaration (ElementTree honors it); raises ValueError on
    malformed XML.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not valid feed XML: {exc}") from exc

    channels = [c for c in root if _local(c.tag) == "channel"]
    holder = channels[0] if channels else root
    feed_title = _child_text(holder, {"title"})

    entries: list[ET.Element] = []
    for parent in (root, *channels):  # root: RSS 1.0 items + Atom entries; channel: RSS 2.0 items
        entries.extend(e for e in parent if _local(e.tag) in ("item", "entry"))

    items: list[Item] = []
    for entry in entries:
        title = _child_text(entry, {"title"})
        link = _entry_link(entry)
        guid = _child_text(entry, {"guid", "id"})
        body = _entry_body(entry)
        when = _child_text(entry, {"pubDate", "updated", "published"})
        meta = {k: v for k, v in (("feed", feed_title), ("date", when)) if v}
        items.append(
            make_item(
                kind="feed-entry", id=guid or link or title, title=title,
                text=body or title, source="feed", ref=link or guid or url,
                method=method, fetched_at=fetched_at, meta=meta,
            )
        )
    return items


class FeedSource:
    """RSS/Atom feed intake via urllib. The isolated impure edge; parsing is pure and tested."""

    name = "feed"

    def __init__(self, *, clock=time.time, timeout: float = 20.0, max_bytes: int = 5_000_000) -> None:
        self._clock = clock
        self._timeout = timeout
        self._max_bytes = max_bytes

    def fetch(self, target: str) -> list[Item]:
        body, _ = http_get(target, timeout=self._timeout, max_bytes=self._max_bytes)
        return parse_feed(body, target, fetched_at=float(self._clock()))  # bytes: ET honors the encoding decl
