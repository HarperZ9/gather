"""gather receipts to organ-bundle interchange entries."""
from __future__ import annotations

from gather.crawl import CrawlLedger, FetchedPage, crawl
from gather.extract import extract
from gather.interop import (
    bundle,
    crawl_entry,
    extraction_entry,
    search_entry,
    validate,
)
from gather.search import SearchHit, search

_HTML = "<html><head><title>T</title></head><body><h1>H</h1><p>p</p></body></html>"


def _crawl_result():
    site = {"http://s.com/": "<a href='/a'>a</a>", "http://s.com/a": "<p>x</p>"}
    return crawl(["http://s.com"], fetcher=lambda u: FetchedPage(u, u, 200 if u in site else 404, site.get(u, "")),
                 obey_robots=False, clock=lambda: 1.0, sleep=lambda s: None)


def test_extraction_and_crawl_entries_form_a_valid_bundle() -> None:
    ex = extract(_HTML, "http://e.com/", fetched_at=1.0)
    res = _crawl_result()
    b = bundle([extraction_entry(ex), crawl_entry(res.ledger)])
    assert validate(b) == []
    # Both ride the registered spine kind; the subtype is in the summary.
    assert {e["receipt_kind"] for e in b["entries"]} == {"gather-corpus"}
    assert any(e["summary"].startswith("[extraction]") for e in b["entries"])
    assert any(e["summary"].startswith("[crawl]") for e in b["entries"])
    assert all(e["organ_id"] == "gather" for e in b["entries"])


def test_crawl_entry_reflects_ledger_integrity() -> None:
    res = _crawl_result()
    assert crawl_entry(res.ledger)["status"] == "pass"
    # A tampered ledger surfaces as a failed entry, not a silent pass.
    from dataclasses import replace
    recs = list(res.ledger.records)
    bad = CrawlLedger((replace(recs[0], status=999),) + tuple(recs[1:]), res.ledger.root_hash)
    assert crawl_entry(bad)["status"] == "fail"


def test_search_lead_entry_is_unverified_without_provider() -> None:
    r = search("q", provider=None)
    assert search_entry(r)["status"] == "unverified"


def test_validate_flags_malformed_entries() -> None:
    b = bundle([{"entry_id": "x", "organ_id": "gather", "receipt_kind": "k",
                 "status": "bogus", "payload_sha256": "nothex", "summary": "s",
                 "payload_ref": "r"}])
    issues = validate(b)
    assert any("bad status" in i for i in issues)
    assert any("64-hex" in i for i in issues)
