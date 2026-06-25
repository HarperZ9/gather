from __future__ import annotations

import subprocess
import time

from gather.item import Item, make_item
from gather.net import validate_public_http_url
from gather.web import html_to_title_text


def parse_browser(html: str, url: str, *, fetched_at: float, method: str = "browser-extract") -> Item:
    """Turn rendered DOM HTML into one webpage Item. Pure: no subprocess. Reuses the web text
    extractor, but the method is ``browser-extract`` (JavaScript WAS run), not ``http-get``, so a
    JS-rendered page is honestly distinguished from a raw fetch."""
    title, text = html_to_title_text(html)
    return make_item(
        kind="webpage", id=url, title=title or url, text=text,
        source="browser", ref=url, method=method, fetched_at=fetched_at,
    )


class BrowserSource:
    """JavaScript-walled page intake via a headless browser. The isolated external-tool edge for
    pages the static `web` adapter can only see the shell of.

    Shells out to a headless Chromium-family browser (an external tool, not a Python dependency)
    to dump the rendered DOM, then extracts text with the pure parser. The receipt's
    ``browser-extract`` method records that JavaScript was executed to produce this text.

    Two safety boundaries an operator must understand, because this edge is more powerful and more
    exposed than the http edge:

    - The scheme + private-host guard is applied only to the INITIAL navigation. Once the page
      loads, a real browser follows its own redirects and loads sub-resources (fetch/XHR, iframes,
      images) with NO host filtering, so a hostile or open-redirecting page can still reach an
      internal address (an SSRF the receipt would then attest as gathered). The DNS-rebinding
      window is wider here than for the http edge. Do not point this at untrusted URLs in an
      environment with reachable internal services.
    - The Chromium sandbox is left ON by default. ``no_sandbox=True`` disables it (sometimes needed
      to run as root in a container) and is a real hardening downgrade while executing untrusted
      JavaScript; use it only when you must, and prefer running as a non-root user instead.

    fetch() needs the browser on PATH and network.
    """

    name = "browser"

    def __init__(self, *, clock=time.time, browser: str = "chromium", timeout: float = 60.0,
                 virtual_time_ms: int = 8000, no_sandbox: bool = False) -> None:
        self._clock = clock
        self._browser = browser
        self._timeout = timeout
        self._virtual_time_ms = virtual_time_ms
        self._no_sandbox = no_sandbox

    def fetch(self, target: str) -> list[Item]:
        url = validate_public_http_url(target)  # guards the INITIAL navigation only (see class doc)
        cmd = [self._browser, "--headless=new", "--disable-gpu"]
        if self._no_sandbox:
            cmd.append("--no-sandbox")
        cmd += [f"--virtual-time-budget={int(self._virtual_time_ms)}", "--dump-dom", url]
        proc = subprocess.run(cmd, capture_output=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"browser failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        html = proc.stdout.decode("utf-8", "replace")
        return [parse_browser(html, url, fetched_at=float(self._clock()))]
