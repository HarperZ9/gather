"""Crawl orchestration + witnessed ledger, offline via a fake fetcher."""
from __future__ import annotations

from dataclasses import replace

from gather.crawl import CrawlLedger, FetchedPage, crawl, default_canonicalize

SITE = {
    "http://s.com/": '<a href="/a">A</a><a href="/b">B</a>',
    "http://s.com/a": '<a href="/c">C</a><a href="/">home</a>',
    "http://s.com/b": '<a href="/c">C</a>',
    "http://s.com/c": "<p>leaf</p>",
}


def fetcher(url: str) -> FetchedPage:
    html = SITE.get(url)
    return FetchedPage(url, url, 200 if html is not None else 404, html or "")


def crawl_site(**kw):
    kw.setdefault("obey_robots", False)
    kw.setdefault("clock", lambda: 1.0)
    kw.setdefault("sleep", lambda s: None)
    return crawl(["http://s.com"], fetcher=fetcher, **kw)


def test_bfs_discovers_all_within_depth() -> None:
    res = crawl_site(max_depth=2, max_pages=50)
    assert set(res.map) == {
        "http://s.com/", "http://s.com/a", "http://s.com/b", "http://s.com/c"}
    assert res.pages == 4


def test_depth_limit_excludes_deeper_pages() -> None:
    res = crawl_site(max_depth=1)
    assert set(res.map) == {"http://s.com/", "http://s.com/a", "http://s.com/b"}


def test_max_pages_caps_the_crawl() -> None:
    assert crawl_site(max_depth=5, max_pages=2).pages == 2


def test_dedup_fetches_shared_child_once() -> None:
    assert crawl_site(max_depth=3).map.count("http://s.com/c") == 1


def test_ledger_verifies_and_tamper_is_detected() -> None:
    res = crawl_site()
    assert res.ledger.verify() is True
    recs = list(res.ledger.records)
    tampered = CrawlLedger((replace(recs[0], status=500),) + tuple(recs[1:]), res.ledger.root_hash)
    assert tampered.verify() is False


def test_robots_blocks_disallowed_url() -> None:
    res = crawl_site(robots=lambda u: not u.endswith("/b"))
    assert "http://s.com/b" not in res.map
    assert "http://s.com/c" in res.map  # still reachable via /a


def test_sitemap_seeds_extra_urls() -> None:
    site = dict(SITE, **{
        "http://s.com/sitemap.xml": "<urlset><url><loc>http://s.com/c</loc></url></urlset>"})

    def f(url):
        html = site.get(url)
        return FetchedPage(url, url, 200 if html is not None else 404, html or "")

    res = crawl(["http://s.com"], fetcher=f, obey_robots=False, include_sitemap=True,
                max_depth=0, clock=lambda: 1.0, sleep=lambda s: None)
    assert {"http://s.com/", "http://s.com/c"}.issubset(set(res.map))


def test_resume_continues_an_unbroken_chain() -> None:
    first = crawl_site(max_pages=1)
    assert first.pages == 1
    second = crawl(["http://s.com"], fetcher=fetcher, obey_robots=False,
                   resume_from=first.state, max_pages=50, clock=lambda: 1.0, sleep=lambda s: None)
    assert second.pages == 4
    assert second.ledger.verify() is True


def test_concurrent_workers_yield_same_pageset() -> None:
    seq = set(crawl_site(workers=1).map)
    par = set(crawl_site(workers=4).map)
    assert seq == par == {
        "http://s.com/", "http://s.com/a", "http://s.com/b", "http://s.com/c"}


def test_canonicalization_dedups_fragment_and_case() -> None:
    assert default_canonicalize("http://S.COM/a#frag") == "http://s.com/a"
    assert default_canonicalize("https://h.com:443/x") == "https://h.com/x"


def test_per_host_throttle_sleeps_between_same_host_requests() -> None:
    waits: list[float] = []
    # A constant clock makes every same-host request appear to need the full floor.
    crawl_site(throttle=5.0, sleep=waits.append, clock=lambda: 0.0)
    assert any(w > 0 for w in waits)      # subsequent same-host fetches wait
    assert all(w <= 5.0 for w in waits)   # never longer than the floor
