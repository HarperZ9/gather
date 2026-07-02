"""Capability backends: resolution, honest UNVERIFIABLE degrade, provenance."""
from __future__ import annotations

from gather.backends import (
    CAP_FAST_PARSE,
    CAP_JS,
    Backend,
    Registry,
    best_parser,
    default_registry,
    detect_fast_parse,
    render,
)


def _browser(html: str) -> Backend:
    return Backend("fake-browser", frozenset({CAP_JS}), handler=lambda url: html)


def test_render_delegates_to_a_capable_backend() -> None:
    reg = Registry().register(_browser("<html>rendered by js</html>"))
    r = render("http://e.com/", registry=reg, require=CAP_JS)
    assert r.status == "rendered"
    assert r.backend == "fake-browser"
    assert "rendered by js" in r.html
    assert r.verify() is True


def test_missing_capability_degrades_to_unverifiable_never_fakes() -> None:
    reg = Registry()  # no js-render backend
    r = render("http://e.com/", registry=reg, require=CAP_JS)
    assert r.status == "UNVERIFIABLE"
    assert r.html == "" and r.content_sha256 == ""
    assert "js-render" in r.reason
    assert r.verify() is True  # an honest UNVERIFIABLE verifies as such


def test_first_registered_wins_capability_tie() -> None:
    reg = (Registry()
           .register(Backend("a", frozenset({CAP_JS}), handler=lambda u: "A"))
           .register(Backend("b", frozenset({CAP_JS}), handler=lambda u: "B")))
    assert render("http://e.com/", registry=reg, require=CAP_JS).backend == "a"


def test_unavailable_backend_is_skipped() -> None:
    reg = (Registry()
           .register(Backend("down", frozenset({CAP_JS}), handler=lambda u: "x",
                             available=lambda: False))
           .register(Backend("up", frozenset({CAP_JS}), handler=lambda u: "y")))
    assert render("http://e.com/", registry=reg, require=CAP_JS).backend == "up"


def test_best_parser_prefers_registered_fast_backend() -> None:
    reg = Registry().register(Backend("turbo", frozenset({CAP_FAST_PARSE})))
    assert best_parser(reg) == "turbo"


def test_best_parser_falls_back_to_stdlib_or_detected_native() -> None:
    # With no registry override, we get whatever is installed, or "stdlib".
    assert best_parser() in ("stdlib", "lxml", "selectolax")
    assert detect_fast_parse() in (None, "lxml", "selectolax")


def test_default_registry_reports_honest_capabilities() -> None:
    reg = default_registry()
    caps = reg.capabilities()
    assert "fetch" in caps  # always present
    # js-render / stealth are unmet unless an optional backend is installed.
    assert reg.has("js-render") is False
    assert reg.has("stealth") is False
