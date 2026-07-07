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
    parser = best_parser(reg)
    caps = reg.capabilities()
    if getattr(args, "json", False):
        print(to_json({"parser": parser, "capabilities": caps}))
    else:
        print(f"parser: {parser}")
        for cap, backends in sorted(caps.items()):
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


def cmd_monitor(args) -> int:
    """Scheduled re-fetch with change custody: diff each source against its
    stored baseline, emit a report, and grow the hash-chained ledger."""
    import json
    import time
    from pathlib import Path

    from gather.fetch import fetch
    from gather.monitor import monitor_pass, verify_ledger

    src_path = Path(args.sources)
    if not src_path.is_file():
        raise SystemExit(f"monitor: --sources file not found: {src_path}")
    sources = [ln.strip() for ln in src_path.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]

    state_path = Path(args.state)
    state = {}
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not verify_ledger(state):
            raise SystemExit(f"monitor: existing ledger {state_path} FAILED its "
                             "hash chain — refusing to append to a tampered record")

    report, new_state = monitor_pass(sources, state, fetch, clock=time.time)
    state_path.write_text(json.dumps(new_state, indent=2), encoding="utf-8")

    if args.json:
        print(to_json(report))
    else:
        c = report["counts"]
        print(f"monitored {report['sources']} source(s): "
              f"{c['NEW']} new, {c['CHANGED']} changed, {c['UNCHANGED']} unchanged, "
              f"{c['GONE']} gone, {c['ERROR']} error")
        for url in report["changed"]:
            print(f"  CHANGED {url}")
        for url in report["gone"]:
            print(f"  GONE    {url}")
        print(f"ledger -> {state_path} ({len(new_state['ledger'])} observations, "
              f"root {new_state['root_hash'][:12]}…)")
    return 1 if (report["counts"]["CHANGED"] or report["counts"]["GONE"]) else 0
