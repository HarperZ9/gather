"""Playwright browser backend: gating and registration (no real launch here)."""
from __future__ import annotations

from importlib.util import find_spec

from gather.backends import CAP_JS, Registry
from gather.backends_browser import browser_backend, playwright_available, register


def test_playwright_available_matches_find_spec() -> None:
    assert playwright_available() == (find_spec("playwright") is not None)


def test_browser_backend_declares_js_render() -> None:
    b = browser_backend()
    assert b.name == "playwright"
    assert CAP_JS in b.capabilities
    assert callable(b.handler)


def test_register_adds_backend_iff_available() -> None:
    reg = Registry()
    register(reg)
    assert reg.has(CAP_JS) == playwright_available()
