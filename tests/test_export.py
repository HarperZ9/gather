"""Uniform JSON / JSONL export across receipt types."""
from __future__ import annotations

import json

from gather.crawl import FetchedPage, crawl
from gather.export import to_dict, to_json, to_jsonl, write_jsonl
from gather.extract import extract
from gather.fetch import RawResponse, fetch

_HTML = "<html><head><title>T</title></head><body><h1>H</h1><p>p</p></body></html>"


def test_to_json_uses_as_dict_and_roundtrips() -> None:
    ex = extract(_HTML, "http://e.com/", fetched_at=1.0)
    parsed = json.loads(to_json(ex))
    assert parsed["url"] == "http://e.com/"
    assert parsed["markdown_sha256"] == ex.markdown_sha256
    assert isinstance(parsed["blocks"], list)


def test_to_json_handles_plain_dataclass_fallback() -> None:
    ok = RawResponse(200, "http://e.com/", (("Content-Type", "text/html"),), b"hi")
    receipt, _ = fetch("http://e.com/", transport=lambda *a, **k: ok, sleep=lambda s: None,
                       clock=lambda: 1.0)
    parsed = json.loads(to_json(receipt))
    assert parsed["status"] == 200 and "content_sha256" in parsed


def test_to_jsonl_one_object_per_line() -> None:
    site = {"http://s.com/": "<a href='/a'>a</a>", "http://s.com/a": "<p>leaf</p>"}
    res = crawl(["http://s.com"], fetcher=lambda u: FetchedPage(u, u, 200 if u in site else 404, site.get(u, "")),
                obey_robots=False, clock=lambda: 1.0, sleep=lambda s: None)
    text = to_jsonl(res.ledger.records)
    lines = text.splitlines()
    assert len(lines) == res.pages
    assert all("entry_hash" in json.loads(ln) for ln in lines)


def test_write_jsonl_roundtrips(tmp_path) -> None:
    out = tmp_path / "records.jsonl"
    write_jsonl(out, [{"a": 1}, {"b": 2}])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln) for ln in lines] == [{"a": 1}, {"b": 2}]


def test_to_dict_is_recursive_on_containers() -> None:
    ex = extract(_HTML, "http://e.com/", fetched_at=1.0)
    d = to_dict([ex, {"nested": ex}])
    assert d[0]["url"] == "http://e.com/"
    assert d[1]["nested"]["url"] == "http://e.com/"
