"""Search intake: lead receipts, honest UNVERIFIABLE, search-then-fetch chain."""
from __future__ import annotations

from gather.item import content_hash
from gather.search import SearchHit, search, search_and_fetch, searx_provider


def fake_provider(query, limit):
    return [
        SearchHit("First", "http://a.com/1", "snip a"),
        SearchHit("Second", "http://b.com/2", "snip b"),
    ][:limit]


fake_provider.provider_name = "fake"


def test_search_returns_verifiable_leads() -> None:
    r = search("q", provider=fake_provider)
    assert r.status == "searched" and r.provider == "fake"
    assert r.urls() == ["http://a.com/1", "http://b.com/2"]
    assert r.hits[0]["url_sha256"] == content_hash("http://a.com/1")
    assert r.verify() is True


def test_search_without_provider_is_unverifiable() -> None:
    r = search("q", provider=None)
    assert r.status == "UNVERIFIABLE"
    assert r.hits == () and "no search provider" in r.reason
    assert r.verify() is True  # honest UNVERIFIABLE


def test_search_and_fetch_chains_to_fetch_receipts() -> None:
    class R:
        status = 200

    def fetcher(url):
        return R(), f"body of {url}".encode()

    receipt, fetched = search_and_fetch("q", provider=fake_provider, fetcher=fetcher, limit=5)
    assert receipt.status == "searched"
    assert [u for u, _fr, _b in fetched] == ["http://a.com/1", "http://b.com/2"]
    assert fetched[0][2] == b"body of http://a.com/1"


def test_searx_provider_parses_json_results() -> None:
    payload = {"results": [
        {"title": "T1", "url": "http://x/1", "content": "c1"},
        {"title": "T2", "url": "http://x/2", "content": "c2"},
    ]}
    provider = searx_provider("http://searx.local", fetch_json=lambda url: payload)
    hits = provider("q", 10)
    assert [h.url for h in hits] == ["http://x/1", "http://x/2"]
    r = search("q", provider=provider)
    assert r.provider.startswith("searxng:")
