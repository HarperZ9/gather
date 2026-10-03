"""CLI glue for ``gather report`` (a cited report from a local model) and ``gather cite-check``
(the citation check alone, on any report text).

Both exit 0 when every citation is verified and 1 when any is not, so either can gate a pipeline.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable


def add_report_parsers(sub, add_common: Callable) -> None:
    from gather.local_model import DEFAULT_ENDPOINT

    rep = sub.add_parser("report", help="write a cited report from excerpts with a local model, citations checked")
    rep.add_argument("question")
    rep.add_argument("--excerpts", required=True, metavar="FILE",
                     help="JSON list of objects with text (and optional title, id, ref)")
    rep.add_argument("--model", required=True, help="the model name your local server knows, e.g. qwen3:8b")
    rep.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                     help=f"OpenAI-compatible endpoint on this machine (default {DEFAULT_ENDPOINT})")
    rep.add_argument("--timeout", type=float, default=600.0, metavar="S", help="seconds for the model's answer")
    add_common(rep)
    rep.set_defaults(func=cmd_report)

    chk = sub.add_parser("cite-check", help="check every citation in a report file against its excerpts")
    chk.add_argument("report", help="a text file holding the report")
    chk.add_argument("--excerpts", required=True, metavar="FILE", help="the excerpts JSON the report cites")
    chk.add_argument("--json", action="store_true", help="emit the check as JSON")
    chk.set_defaults(func=cmd_cite_check)


def _summary(check: dict) -> str:
    counts = ", ".join(f"{k} {v}" for k, v in check["counts"].items() if v)
    return (f"citations: {check['total']} ({counts or 'none'}); precision {check['precision']}; "
            f"uncited sentences: {len(check['uncited_sentences'])}")


def _all_verified(check: dict) -> bool:
    return check["total"] > 0 and check["counts"]["verified"] == check["total"]


def cmd_report(args) -> int:
    from gather.commands import _emit, _scope
    from gather.local_model import LocalModel
    from gather.report import load_excerpts, write_report

    try:
        model = LocalModel(args.model, endpoint=args.endpoint, timeout=args.timeout)
        item = write_report(args.question, load_excerpts(args.excerpts), model)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        return 2
    check = item.meta["citation_check"]
    if args.json:
        print(json.dumps({"report": item.text, "meta": item.meta, "sha256": item.provenance.sha256,
                          "derived_from": list(item.provenance.derived_from)}, indent=2, ensure_ascii=False))
    else:
        print(item.text)
        print(f"\n{_summary(check)}")
    if args.store:
        _emit([item], _scope(args), False, store=args.store)
    return 0 if _all_verified(check) else 1


def cmd_cite_check(args) -> int:
    from gather.citecheck import check_report
    from gather.report import load_excerpts

    try:
        with open(args.report, encoding="utf-8") as f:
            text = f.read()
        excerpts = [it.text for it in load_excerpts(args.excerpts)]
    except (ValueError, OSError) as exc:
        print(f"cite-check failed: {exc}", file=sys.stderr)
        return 2
    check = check_report(text, excerpts)
    print(json.dumps(check, indent=2, ensure_ascii=False) if args.json else _summary(check))
    return 0 if _all_verified(check) else 1
