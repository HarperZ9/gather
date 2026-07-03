"""Native (lxml) parsing produces the same accountable Node tree as stdlib."""
from __future__ import annotations

import pytest

from gather.dom import find, parse_dom, select
from gather.fastparse import parse_best, parse_dom_lxml

FIXTURE = (
    "<html><body><div class='c'><p>a</p><p>b</p></div>"
    "<a href='/x'>link</a></body></html>"
)


def _paths(root, sel):
    return [n.path for n in select(root, sel)]


def test_lxml_matches_stdlib_paths() -> None:
    pytest.importorskip("lxml")
    std, fast = parse_dom(FIXTURE), parse_dom_lxml(FIXTURE)
    for sel in ("p", ".c", "a", "div"):
        assert _paths(fast, sel) == _paths(std, sel), sel


def test_lxml_preserves_text_and_attrs() -> None:
    pytest.importorskip("lxml")
    fast = parse_dom_lxml(FIXTURE)
    assert find(fast, "p").text_content() == "a"
    assert find(fast, "a").attrs.get("href") == "/x"


def test_parse_best_returns_a_working_tree() -> None:
    root = parse_best(FIXTURE)
    assert [n.text_content() for n in select(root, "p")] == ["a", "b"]
