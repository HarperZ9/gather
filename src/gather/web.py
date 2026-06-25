from __future__ import annotations

import time
from html.parser import HTMLParser

from gather.item import Item, make_item
from gather.net import decode_body, http_get

_SKIP = {"script", "style", "noscript", "template", "svg"}
_BLOCK = {
    "p", "div", "br", "li", "tr", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre",
}


class _HTMLText(HTMLParser):
    """Extracts the readable text and the title from HTML. Drops script/style, inserts
    breaks on block elements, and decodes entities (convert_charrefs)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._title: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title.append(data)
        else:
            self._chunks.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title).split())

    @property
    def text(self) -> str:
        lines = (" ".join(ln.split()) for ln in "".join(self._chunks).splitlines())
        return "\n".join(ln for ln in lines if ln)


def html_to_title_text(html: str) -> tuple[str, str]:
    """Return ``(title, readable_text)`` for an HTML document. Pure and deterministic.

    A static-HTML reader: it sees what the server sent. It does not run JavaScript, so a
    page whose content is rendered client-side yields only its shell. That limit is real and
    is why the receipt's method is "http-get" (a raw fetch), not a claim of a rendered page.
    """
    p = _HTMLText()
    p.feed(html)
    p.close()
    return p.title, p.text


def parse_web(html: str, url: str, *, fetched_at: float, method: str = "http-get") -> Item:
    """Turn fetched HTML into one webpage Item with a provenance receipt. Pure: no network."""
    title, text = html_to_title_text(html)
    return make_item(
        kind="webpage", id=url, title=title or url, text=text,
        source="web", ref=url, method=method, fetched_at=fetched_at,
    )


class WebSource:
    """Static web-page intake via urllib. The isolated impure edge for the open web.

    Fetches the raw HTML the server returns and extracts readable text with the pure
    parser. It does not execute JavaScript: a client-rendered page yields only its shell,
    and the "http-get" method on the receipt says exactly that, so a thin result is never
    mistaken for the full page. A browser-backed adapter for JS-walled pages is a separate,
    later edge. fetch() needs network.
    """

    name = "web"

    def __init__(self, *, clock=time.time, timeout: float = 20.0) -> None:
        self._clock = clock
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        body, ctype = http_get(target, timeout=self._timeout)
        html = decode_body(body, ctype)
        return [parse_web(html, target, fetched_at=float(self._clock()))]
