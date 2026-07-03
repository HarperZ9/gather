"""Honest micro-benchmark of gather's zero-dep parse / select / extract.

Reports gather's REAL numbers over a ~5000-element document (the size Scrapling
publishes). The competitor figures quoted in the docs are their PUBLISHED numbers,
not re-run here. Run:  python examples/bench.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gather.dom import parse_dom, select  # noqa: E402
from gather.extract import extract, to_markdown  # noqa: E402


def make_html(n: int) -> str:
    rows = "".join(
        f'<div class="r"><p>item {i} of the document body text</p>'
        f'<a href="/x{i}">link {i}</a></div>'
        for i in range(n)
    )
    return f"<html><head><title>bench</title></head><body>{rows}</body></html>"


def bench(thunk, iters: int = 7) -> float:
    return min(_timed(thunk) for _ in range(iters))


def _timed(thunk) -> float:
    start = time.perf_counter()
    thunk()
    return (time.perf_counter() - start) * 1000.0


def main() -> int:
    html = make_html(5000)
    root = parse_dom(html)
    print(f"document: {len(html):,} bytes, ~5000 elements, zero dependencies")
    print(f"  parse_dom      {bench(lambda: parse_dom(html)):7.2f} ms  [stdlib, zero-dep]")
    try:
        from gather.backends import detect_fast_parse
        from gather.fastparse import parse_dom_lxml
        if detect_fast_parse() == "lxml":
            print(f"  parse (lxml)   {bench(lambda: parse_dom_lxml(html)):7.2f} ms  [fast-parse backend]")
    except Exception:  # pragma: no cover - optional
        pass
    print(f"  select('.r')   {bench(lambda: select(root, '.r')):7.2f} ms "
          f"({len(select(root, '.r'))} hits)")
    print(f"  to_markdown    {bench(lambda: to_markdown(html)):7.2f} ms")
    print(f"  extract        {bench(lambda: extract(html, 'http://e.com/', fetched_at=1.0)):7.2f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
