from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from gather.item import Item, make_item
from gather.net import http_get

ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$|^[a-z-]+(\.[A-Za-z-]+)?/\d{7}(v\d+)?$", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _arxiv_id(id_url: str) -> str:
    """The bare arXiv id from an abs URL: http://arxiv.org/abs/2301.12345v2 -> 2301.12345v2."""
    if "/abs/" in id_url:
        return id_url.split("/abs/", 1)[1].rstrip("/")
    return id_url.rsplit("/", 1)[-1]


def arxiv_query_url(target: str, *, max_results: int = 10) -> str:
    """Build the arXiv API URL for a target. Pure and deterministic.

    A bare arXiv id (``2301.12345``, optionally versioned, or an old ``cs.AI/0601001``) is
    fetched by id; anything else is treated as a free-text search over all fields, returning
    up to ``max_results`` by relevance.
    """
    target = target.strip()
    if _ARXIV_ID.match(target):
        params = {"id_list": target, "max_results": "1"}
    else:
        params = {
            "search_query": f"all:{target}", "start": "0",
            "max_results": str(max_results), "sortBy": "relevance",
        }
    return f"{ARXIV_API}?{urllib.parse.urlencode(params)}"


def parse_arxiv(xml: str | bytes, *, fetched_at: float, method: str = "arxiv-api") -> list[Item]:
    """Parse an arXiv API Atom response into one paper Item per entry. Pure: no network.

    Each Item's text is the ABSTRACT, not the full paper (the API returns abstracts); the PDF
    link is recorded in ``meta`` for the separate full-text adapter, so an abstract is never
    mistaken for the paper. Authors, categories, primary category, publication date, and DOI
    are carried in ``meta``. Raises ValueError on malformed XML.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not valid arXiv API XML: {exc}") from exc

    items: list[Item] = []
    for entry in (e for e in root if _local(e.tag) == "entry"):
        id_url = title = abstract = published = primary = doi = pdf = ""
        authors: list[str] = []
        cats: list[str] = []
        for ch in entry:
            n = _local(ch.tag)
            if n == "id":
                id_url = (ch.text or "").strip()
            elif n == "title":
                title = " ".join((ch.text or "").split())
            elif n == "summary":
                abstract = " ".join("".join(ch.itertext()).split())
            elif n == "published":
                published = (ch.text or "").strip()
            elif n == "author":
                authors.extend(s.text.strip() for s in ch if _local(s.tag) == "name" and s.text)
            elif n == "primary_category":
                primary = ch.get("term") or primary
            elif n == "category":
                term = ch.get("term")
                if term:
                    cats.append(term)
            elif n == "link" and (ch.get("title") == "pdf" or ch.get("type") == "application/pdf"):
                pdf = ch.get("href") or pdf
            elif n == "doi":
                doi = (ch.text or "").strip()
        meta: dict[str, object] = {}
        for key, val in (("authors", authors), ("published", published), ("primary_category", primary),
                         ("categories", cats), ("pdf", pdf), ("doi", doi)):
            if val:
                meta[key] = val
        items.append(
            make_item(
                kind="paper", id=_arxiv_id(id_url) or id_url, title=title, text=abstract,
                source="arxiv", ref=id_url or _arxiv_id(id_url), method=method,
                fetched_at=fetched_at, meta=meta,
            )
        )
    return items


class ArxivSource:
    """arXiv paper intake via the public arXiv API. The isolated impure edge; parsing is pure.

    fetch(target) takes an arXiv id or a free-text query and returns paper Items carrying the
    abstract and metadata. Needs network. The full text behind the PDF link is a separate
    adapter (see gather.pdf); this returns abstracts, and the receipt's method says so.
    """

    name = "arxiv"

    def __init__(self, *, clock=time.time, timeout: float = 20.0, max_results: int = 10) -> None:
        self._clock = clock
        self._timeout = timeout
        self._max_results = max_results

    def fetch(self, target: str) -> list[Item]:
        url = arxiv_query_url(target, max_results=self._max_results)
        body, _ = http_get(url, timeout=self._timeout)
        return parse_arxiv(body, fetched_at=float(self._clock()))
