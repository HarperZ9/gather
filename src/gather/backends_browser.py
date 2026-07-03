"""JS-render backend over Playwright (wedge 5, browser-use / Scrapling-Dynamic
parity).

Registers a ``js-render`` capability when Playwright is importable. The handler
renders a URL to its post-JavaScript HTML. If Playwright is present but the
browser binary is not installed (``playwright install chromium``), the render
raises and ``backends.render`` reports UNVERIFIABLE with the reason, never a fake.

Optional: install with ``pip install 'gather-engine[browser]'`` then
``playwright install chromium``. Absent, the js-render capability is simply
unmet.
"""
from __future__ import annotations

from importlib.util import find_spec

from gather.backends import CAP_JS, Backend, Registry
from gather.net import validate_public_http_url


def playwright_available() -> bool:
    return find_spec("playwright") is not None


def render_playwright(url: str, *, timeout_ms: int = 20000, wait_until: str = "load") -> str:
    """Return the post-JavaScript HTML of ``url``. Requires Playwright + a browser
    binary. Enforces the same scheme/SSRF guard as the stdlib fetch edge."""
    url = validate_public_http_url(url)
    from playwright.sync_api import sync_playwright  # type: ignore

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until=wait_until)
            return page.content()
        finally:
            browser.close()


def browser_backend() -> Backend:
    return Backend(
        "playwright", frozenset({CAP_JS}),
        handler=render_playwright, available=playwright_available,
    )


def register(registry: Registry) -> Registry:
    """Register the browser backend if Playwright is importable."""
    if playwright_available():
        registry.register(browser_backend())
    return registry
