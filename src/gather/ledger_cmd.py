"""CLI glue for ``gather ledger verify``: recompute a filter ledger from its input file.

Exit status 0 when every count recomputes, 1 when any does not, 2 when a file cannot be read.
"""

from __future__ import annotations

import json
import os
import sys


def add_ledger_parser(sub) -> None:
    led = sub.add_parser("ledger", help="verify a filter ledger against its input file")
    led_sub = led.add_subparsers(dest="ledger_command", required=True)
    ver = led_sub.add_parser("verify", help="recompute every count in a filter ledger")
    ver.add_argument("ledger", help="a ledger.json, or the folder holding ledger.json and input.jsonl")
    ver.add_argument("input", nargs="?", default=None, help="the input.jsonl (default: beside the ledger)")
    ver.add_argument("--json", action="store_true", help="emit the result as JSON")
    ver.set_defaults(func=cmd_ledger_verify)


def cmd_ledger_verify(args) -> int:
    from gather.ledger_verify import verify_files

    ledger = os.path.join(args.ledger, "ledger.json") if os.path.isdir(args.ledger) else args.ledger
    input_path = args.input or os.path.join(os.path.dirname(ledger), "input.jsonl")
    try:
        problems = verify_files(ledger, input_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ledger verify failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"verified": not problems, "problems": problems}, indent=2))
    else:
        print("ledger verified: every count recomputes" if not problems else "ledger does not recompute:")
        for p in problems:
            print(f"  {p}")
    return 0 if not problems else 1
