"""Honest, reproducible micro-benchmark of gather's zero-dep parse / select / extract.

Reports an INTERVAL per operation (min / median / max over N runs), not a single
number, and can write the whole evidence artifact (environment + document + stats)
to JSON so a reader can inspect and reproduce it.

  python examples/bench.py                       # print the interval table
  python examples/bench.py --out bench.json      # + write the evidence artifact
  python examples/bench.py --elements 5000 --iters 9
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gather.benchmark import run_suite  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--elements", type=int, default=5000)
    ap.add_argument("--iters", type=int, default=7)
    ap.add_argument("--out", default="", help="write the evidence artifact (JSON) here")
    args = ap.parse_args(argv)

    ev = run_suite(elements=args.elements, iters=args.iters)
    d = ev["document"]
    print(f"document: {d['bytes']:,} bytes, ~{d['elements']} elements, zero dependencies "
          f"({ev['iters']} iters)")
    print(f"  {'op':16} {'median':>9} {'min':>9} {'max':>9}")
    for o in ev["ops"]:
        tag = "  [fast-parse]" if o["op"].endswith("_lxml") else ""
        print(f"  {o['op']:16} {o['median_ms']:7.2f}ms {o['min_ms']:7.2f}ms "
              f"{o['max_ms']:7.2f}ms{tag}")
    if args.out:
        Path(args.out).write_text(json.dumps(ev, indent=2), encoding="utf-8")
        print(f"\nevidence written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
