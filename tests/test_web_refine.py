"""Regression tests for the adversarial-review fixes (the refine pass).

Each test is the negative that the review found and would have caught: a receipt
that verified when it shouldn't, a capability leak, or a crash on realistic input.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import gather.backends_stealth as bs
from gather.cache import ResponseCache, cached_fetch
from gather.dom import find, parse_dom, select
from gather.export import to_dict, to_json
from gather.fastparse import parse_dom_lxml
from gather.interop import validate
from gather.schema_extract import Field, extract_schema, verify_record
from gather.search import SearchReceipt
from gather.track import fingerprint, relocate


# Fix 1: lxml wraps a fragment in html/body; paths must still match stdlib.
def test_fix1_lxml_fragment_paths_match_stdlib() -> None:
    pytest.importorskip("lxml")
    frag = "<p>alpha</p><p>beta</p>"
    std, fast = parse_dom(frag), parse_dom_lxml(frag)
    assert [n.path for n in select(fast, "p")] == [n.path for n in select(std, "p")] == ["p[1]", "p[2]"]


def test_fix1_relocate_is_match_across_parsers_for_a_fragment() -> None:
    pytest.importorskip("lxml")
    frag = "<p id='x'>hello world</p>"
    fp = fingerprint(find(parse_dom(frag), "p"))
    assert relocate(fp, parse_dom_lxml(frag)).verdict == "MATCH"  # not a false RELOCATED


# Fix 2: a tampered value that is a substring of the source must fail verify().
def test_fix2_tampered_substring_value_fails_verify() -> None:
    html = "<html><body><span class='c'>category</span></body></html>"
    ex = extract_schema(html, {"c": Field("span.c")}, "u", fetched_at=1.0)
    assert ex.verify(html) is True
    f = ex.fields[0]
    forged = replace(ex, fields=(replace(f, hits=(replace(f.hits[0], value="cat"),)),))
    assert forged.verify(html) is False


# Fix 3: verify_record grounds on word boundaries, so 100 != inside 1000.
def test_fix3_verify_record_word_boundary_numeric() -> None:
    html = "<html><body><p>Total price: $1000</p></body></html>"
    assert verify_record(html, {"price": "1000"}).ok is True
    assert verify_record(html, {"price": "100"}).ok is False


# Fix 4: a 304 with no cache entry to revalidate against must be refused.
def test_fix4_304_without_cache_entry_is_refused(tmp_path) -> None:
    class R:
        status, not_modified, etag, last_modified = 304, True, "", ""

    def ff(url, *, etag, last_modified, **kw):
        return R(), None

    with pytest.raises(ValueError):
        cached_fetch("http://e.com/", cache=ResponseCache(tmp_path), fetch_fn=ff,
                     revalidate=True, clock=lambda: 1.0)


# Fix 5: credentials must be stripped on an https->http downgrade redirect.
def test_fix5_downgrade_redirect_strips_credentials(monkeypatch) -> None:
    monkeypatch.setattr(bs, "validate_public_http_url", lambda u: u)

    class Resp:
        def __init__(self, s, h=None, c=b""):
            self.status_code, self.headers, self.content = s, h or {}, c

    class Client:
        def __init__(self, *r):
            self.r, self.calls = list(r), []

        def get(self, url, *, headers, timeout, impersonate, allow_redirects):
            self.calls.append(dict(headers))
            return self.r.pop(0)

    client = Client(Resp(302, {"location": "http://e.com/x"}), Resp(200, {}, b"ok"))
    bs.stealth_transport("https://e.com/", headers={"Authorization": "Bearer t", "User-Agent": "x"},
                         timeout=5, max_bytes=100, client=client)
    assert "Authorization" not in client.calls[1]   # dropped on the http hop
    assert "User-Agent" in client.calls[1]


# Fix 6: urls() must not crash on a hit dict missing 'url'.
def test_fix6_urls_survives_partial_hit() -> None:
    r = SearchReceipt("q", "p", "searched", "search-lead", hits=({"title": "t"},))
    assert r.urls() == [""]


# Fix 7/9: validate() must report malformed input, never raise.
def test_fix7_validate_reports_instead_of_raising() -> None:
    assert validate(None) == ["bundle is not an object"]
    assert validate("x") == ["bundle is not an object"]
    assert validate({"entries": None}) == ["bundle entries is not a list"]
    assert validate({"entries": [123]}) == ["entry[0] is not an object"]
    assert validate({"entries": [["a"]]}) == ["entry[0] is not an object"]


# Fix 8: a reference cycle raises a clean ValueError, not RecursionError.
def test_fix8_cycle_raises_valueerror() -> None:
    d = {"a": 1}
    d["self"] = d
    with pytest.raises(ValueError):
        to_dict(d)


def test_fix8_shared_acyclic_reference_still_serializes() -> None:
    shared = {"k": 1}
    assert to_dict({"x": shared, "y": shared}) == {"x": {"k": 1}, "y": {"k": 1}}


# Fix 10: a non-serializable leaf falls back to str instead of crashing.
def test_fix10_non_serializable_leaf_uses_default_str() -> None:
    import json

    class C:
        def __repr__(self):
            return "C()"

    assert json.loads(to_json({"obj": C()}))["obj"] == "C()"
