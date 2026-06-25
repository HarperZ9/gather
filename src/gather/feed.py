from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from gather.item import Item, make_item
from gather.net import decode_body, http_get


def _local(tag: str) -> str:
    """The local name of a possibly namespaced XML tag (Atom namespaces it, RSS does not)."""
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element, names: set[str]) -> str:
    for child in parent:
        if _local(child.tag) in names:
            return (child.text or "").strip()
    return ""


def _entry_link(entry: ET.Element) -> str:
    """The best link for an entry: RSS <link>text, or Atom <link href> preferring alternate."""
    link = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if href:
            if child.get("rel", "alternate") == "alternate" or not link:
                link = href
        elif child.text:
            link = child.text.strip()
    return link


def parse_feed(xml: str, url: str, *, fetched_at: float, method: str = "feed") -> list[Item]:
    """Parse an RSS or Atom feed into one Item per entry. Pure: no network.

    Handles both RSS (``channel/item``) and Atom (``feed/entry``) by local tag name, so a
    namespaced Atom feed and a bare RSS feed both work. Each entry becomes a "feed-entry"
    Item: the link (or guid/id) is the ref, the description/summary/content is the text.
    Raises ValueError on malformed XML.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not valid feed XML: {exc}") from exc

    holder = next((e for e in root if _local(e.tag) == "channel"), root)  # RSS nests, Atom does not
    feed_title = _child_text(holder, {"title"})

    items: list[Item] = []
    for entry in (e for e in root.iter() if _local(e.tag) in ("item", "entry")):
        title = _child_text(entry, {"title"})
        link = _entry_link(entry)
        guid = _child_text(entry, {"guid", "id"})
        body = ""
        for child in entry:
            if _local(child.tag) in ("description", "summary", "content"):
                body = "".join(child.itertext()).strip()
                if body:
                    break
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

    def __init__(self, *, clock=time.time, timeout: float = 20.0) -> None:
        self._clock = clock
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        body, ctype = http_get(target, timeout=self._timeout)
        return parse_feed(decode_body(body, ctype), target, fetched_at=float(self._clock()))
