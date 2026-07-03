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


def test_render_degrades_when_backend_fails_never_fakes() -> None:
    def boom(url):
        raise RuntimeError("browser binary not installed")

    reg = Registry().register(Backend("playwright", frozenset({CAP_JS}), handler=boom))
    r = render("http://e.com/", registry=reg, require=CAP_JS)
    assert r.status == "UNVERIFIABLE"
    assert r.backend == "playwright"      # names which backend failed
    assert "browser binary" in r.reason
    assert r.html == ""                   # no fabricated render


def test_default_registry_reports_honest_capabilities() -> None:
    from importlib.util import find_spec

    reg = default_registry()
    assert "fetch" in reg.capabilities()  # always present
    # Capabilities are reported iff their optional backend is actually installed.
    assert reg.has("js-render") == (find_spec("playwright") is not None)
    assert reg.has("stealth") == (find_spec("curl_cffi") is not None)
    assert reg.has("fast-parse") == (
        find_spec("lxml") is not None or find_spec("selectolax") is not None)
