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
    to dump the rendered DOM, then extracts text with the pure parser. The same scheme + private
    host SSRF guard the http edge uses is applied to the target. The receipt's ``browser-extract``
    method records that JavaScript was executed to produce this text. fetch() needs the browser on
    PATH and network.
    """

    name = "browser"

    def __init__(self, *, clock=time.time, browser: str = "chromium", timeout: float = 60.0,
                 virtual_time_ms: int = 8000) -> None:
        self._clock = clock
        self._browser = browser
        self._timeout = timeout
        self._virtual_time_ms = virtual_time_ms

    def fetch(self, target: str) -> list[Item]:
        url = validate_public_http_url(target)  # scheme + private-host guard, same as http_get
        cmd = [
            self._browser, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--virtual-time-budget={int(self._virtual_time_ms)}", "--dump-dom", url,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"browser failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        html = proc.stdout.decode("utf-8", "replace")
        return [parse_browser(html, url, fetched_at=float(self._clock()))]
