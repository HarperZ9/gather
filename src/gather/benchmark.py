"""benchmark.py -- an honest, reproducible micro-benchmark of gather's zero-dep core.

A benchmark that reports one number hides its own variance. This one reports an
INTERVAL per operation (min / median / max over N iterations) and returns a
serializable evidence artifact -- the environment it ran in, the document it ran
over, and the per-op stats -- so a reader can inspect it, reproduce it, and compare
like with like. Absolute milliseconds are machine-specific; the interval and the
recorded environment are what make the numbers honest rather than a single boast.

Zero-dep (stdlib only). Timings use time.perf_counter; stats use statistics.median.
"""
from __future__ import annotations

import platform
import statistics
import sys
import time

SCHEMA = "gather.benchmark/v1"


def measure(thunk, *, iters: int = 7) -> dict:
    """Run ``thunk`` ``iters`` times and report the interval, not a single number.

    Returns {iters, min_ms, median_ms, max_ms}. min is the least-perturbed run
    (closest to the true cost); median and max expose the spread a single-number
    benchmark would hide."""
    if iters < 1:
        raise ValueError("iters must be >= 1")
    samples = []
    for _ in range(iters):
        start = time.perf_counter()
        thunk()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {"iters": iters,
            "min_ms": round(min(samples), 4),
            "median_ms": round(statistics.median(samples), 4),
            "max_ms": round(max(samples), 4)}


def _make_html(elements: int) -> str:
    rows = "".join(
        f'<div class="r"><p>item {i} of the document body text</p>'
        f'<a href="/x{i}">link {i}</a></div>'
        for i in range(elements)
    )
    return f"<html><head><title>bench</title></head><body>{rows}</body></html>"


def _env() -> dict:
    return {"python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine() or "unknown"}


def run_suite(*, elements: int = 5000, iters: int = 7) -> dict:
    """Benchmark parse / select / markdown / extract over a generated document and
    return an evidence artifact (schema, env, document descriptor, per-op intervals).
    Each op row carries a ``detail`` witnessing what it actually did (e.g. hit count),
    so the number is anchored to a measured fact, not an assumed one."""
    from gather.dom import parse_dom, select
    from gather.extract import extract, to_markdown

    html = _make_html(elements)
    root = parse_dom(html)
    hits = len(select(root, ".r"))
    ops = [
        {"op": "parse_dom", "detail": {"elements": elements},
         **measure(lambda: parse_dom(html), iters=iters)},
        {"op": "select", "detail": {"selector": ".r", "hits": hits},
         **measure(lambda: select(root, ".r"), iters=iters)},
        {"op": "to_markdown", "detail": {},
         **measure(lambda: to_markdown(html), iters=iters)},
        {"op": "extract", "detail": {"note": "markdown + per-block receipt"},
         **measure(lambda: extract(html, "http://e.com/", fetched_at=1.0), iters=iters)},
    ]
    # a fast-parse backend, when installed, is reported alongside (never instead of)
    # the zero-dep number, so the honest default is always visible.
    try:
        from gather.backends import detect_fast_parse
        from gather.fastparse import parse_dom_lxml
        if detect_fast_parse() == "lxml":
            ops.append({"op": "parse_dom_lxml", "detail": {"backend": "lxml"},
                        **measure(lambda: parse_dom_lxml(html), iters=iters)})
    except Exception:  # pragma: no cover - optional backend
        pass
    return {"schema": SCHEMA, "env": _env(),
            "document": {"bytes": len(html), "elements": elements},
            "iters": iters, "ops": ops}
