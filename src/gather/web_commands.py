"""CLI handlers for the web-data capabilities: caps, extract, markdown, crawl.

Each prints a receipt as JSON so the accountability is on the command line, not
just the library. ``extract`` and ``markdown`` accept a local file (offline) or a
URL (fetched through the accountable path); ``caps`` is offline and reports what
this install can actually do.
"""
from __future__ import annotations

import os

from gather.backends import best_parser, default_registry
from gather.export import to_json
from gather.extract import extract, to_markdown


def _read_source(target: str) -> tuple[str, str]:
    if os.path.isfile(target):
        with open(target, encoding="utf-8", errors="replace") as fh:
            return fh.read(), f"file://{os.path.abspath(target)}"
    from gather.fetch import fetch_text

    _receipt, text = fetch_text(target)
    return (text or ""), target


def cmd_caps(args) -> int:
    reg = default_registry()
    info = {"parser": best_parser(reg), "capabilities": reg.capabilities()}
    if getattr(args, "json", False):
        print(to_json(info))
    else:
        print(f"parser: {info['parser']}")
        for cap, backends in sorted(info["capabilities"].items()):
            print(f"  {cap:<12} {', '.join(backends)}")
    return 0


def cmd_extract(args) -> int:
    html, url = _read_source(args.target)
    print(to_json(extract(html, url, fetched_at=0.0)))
    return 0


def cmd_markdown(args) -> int:
    html, _url = _read_source(args.target)
    print(to_markdown(html))
    return 0


def cmd_crawl(args) -> int:
    from gather.crawl import FetchedPage, crawl
    from gather.fetch import fetch_text

    def fetcher(url: str) -> FetchedPage:
        receipt, text = fetch_text(url)
        return FetchedPage(url, receipt.final_url, receipt.status, text or "")

    res = crawl([args.url], fetcher=fetcher, max_depth=args.depth, max_pages=args.max_pages)
    print(to_json(res.ledger))
    return 0
