"""Search + agent intake: turn a query into fetchable, receipted leads.

Firecrawl's search/agent lets you gather without a URL. gather does the same
through a pluggable provider seam, and keeps it honest: search results are
SOURCE_LEADs, not verified content, so the SearchReceipt says so. The verified
content comes from fetching each lead through the accountable fetch path, where
it gets its own re-verifiable receipt.

    search(query, provider=p)            -> SearchReceipt (leads)
    search_and_fetch(query, provider=p, fetcher=f) -> leads + fetch receipts

No provider is bundled (search engines need an endpoint or key). A provider is a
callable ``(query, limit) -> list[SearchHit]``; ``searx_provider`` wires a
self-hostable SearXNG instance with no API key. Absent a provider, search returns
UNVERIFIABLE rather than inventing results.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from gather.item import content_hash

SearchProvider = Callable[..., list]  # (query, limit) -> list[SearchHit]


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SearchReceipt:
    query: str
    provider: str
    status: str          # "searched" | "UNVERIFIABLE"
    method: str
    hits: tuple[dict, ...] = ()   # {title, url, snippet, url_sha256}
    reason: str = ""

    def verify(self) -> bool:
        if self.status != "searched":
            return not self.hits
        return all(h.get("url_sha256") == content_hash(h.get("url", "")) for h in self.hits)

    def urls(self) -> list[str]:
        return [h.get("url", "") for h in self.hits]

    def as_dict(self) -> dict:
        return {
            "query": self.query, "provider": self.provider, "status": self.status,
            "method": self.method, "reason": self.reason, "hits": list(self.hits),
        }


def search(query: str, *, provider: SearchProvider | None = None, limit: int = 10) -> SearchReceipt:
    """Run ``query`` through ``provider`` and return a lead receipt. With no
    provider, returns UNVERIFIABLE (never fabricated results)."""
    if provider is None:
        return SearchReceipt(query, "", "UNVERIFIABLE", "search-lead",
                             reason="no search provider configured")
    hits = provider(query, limit)
    packed = tuple(
        {"title": h.title, "url": h.url, "snippet": h.snippet,
         "url_sha256": content_hash(h.url)}
        for h in hits[:limit]
    )
    name = getattr(provider, "provider_name", getattr(provider, "__name__", "provider"))
    return SearchReceipt(query, name, "searched", "search-lead", hits=packed)


def search_and_fetch(query: str, *, provider: SearchProvider, fetcher: Callable,
                     limit: int = 5) -> tuple[SearchReceipt, list]:
    """Search, then fetch each lead through the accountable fetch path. Returns
    ``(search_receipt, [(url, fetch_receipt, body), ...])``. The search gives
    leads; each fetch gives a re-verifiable content receipt."""
    receipt = search(query, provider=provider, limit=limit)
    fetched = []
    for url in receipt.urls():
        try:
            fr, body = fetcher(url)
        except Exception:
            continue
        fetched.append((url, fr, body))
    return receipt, fetched


def searx_provider(base_url: str, *, fetch_json: Callable | None = None) -> SearchProvider:
    """A no-API-key provider backed by a self-hosted SearXNG JSON endpoint.
    ``fetch_json(url) -> dict`` is injectable for testing; the default fetches
    over the accountable path."""
    def _default_fetch_json(url: str) -> dict:
        from gather.fetch import fetch
        _receipt, body = fetch(url)
        return json.loads((body or b"{}").decode("utf-8", "replace"))

    fetch_json = fetch_json or _default_fetch_json

    def provider(query: str, limit: int) -> list[SearchHit]:
        from urllib.parse import quote
        url = f"{base_url.rstrip('/')}/search?q={quote(query)}&format=json"
        data = fetch_json(url)
        out = []
        for r in (data.get("results") or [])[:limit]:
            out.append(SearchHit(r.get("title", ""), r.get("url", ""), r.get("content", "")))
        return out

    provider.provider_name = f"searxng:{base_url}"  # type: ignore[attr-defined]
    return provider
