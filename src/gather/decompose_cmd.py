"""CLI glue for ``gather decompose`` and ``gather rebuild``.

``gather decompose FILE --out DIR`` takes one local file apart into a tree (``tree.json`` plus
``parts/``) by fixed rules: the handler is chosen from the file's bytes, every byte is kept, and
the same file gives the same tree. ``gather rebuild DIR --out FILE`` puts the file back together
byte for byte and checks every node; ``--verify`` checks without writing.

Exit status: 0 on success; 1 when a rebuild or a verify finds a node that fails its check; 2 on
bad options, an input that is not a local file, or a tree that cannot be read.
"""

from __future__ import annotations

import json
import sys


def add_decompose_parsers(sub) -> None:
    d = sub.add_parser("decompose", help="take one local file apart into a tree of its parts, offline, by fixed rules")
    d.add_argument("file", help="a local file; it is read as data and never executed")
    d.add_argument("--out", required=True, metavar="DIR", help="an empty or new folder for tree.json and parts/")
    d.add_argument("--no-content", action="store_true", help="write the structural tree only, no measurement tables")
    d.add_argument("--json", action="store_true", help="print the summary as JSON")
    d.set_defaults(func=cmd_decompose)

    r = sub.add_parser("rebuild", help="rebuild a file byte for byte from a decompose tree, checking every node")
    r.add_argument("tree", help="a folder written by gather decompose")
    r.add_argument("--out", metavar="FILE", help="the file to write")
    r.add_argument("--verify", action="store_true", help="check the tree without writing a file")
    r.add_argument("--companion", metavar="NAME", help="rebuild a companion file recorded in the tree instead")
    r.add_argument("--json", action="store_true", help="print the report as JSON")
    r.set_defaults(func=cmd_rebuild)


def summary(doc: dict) -> dict:
    """The facts about a tree worth printing: no node list, no local path."""
    return {"format": doc["format"], "source": doc["source"], "handler": doc["handler"], "declined": doc["declined"],
            "rebuild": doc["rebuild"], "unparsed_bytes": sum(r["length"] for r in doc["unparsed"]),
            "companions": [c["name"] for c in doc.get("companions", [])],
            "content": {row["component"]: row["status"] for row in doc.get("content", [])}}


def cmd_decompose(args) -> int:
    from gather.decompose_run import decompose_file
    from gather.localpath import require_local

    try:
        doc = decompose_file(require_local(args.file, label="file"), args.out, content=not args.no_content)
    except (OSError, ValueError) as exc:
        print(f"decompose: {exc}", file=sys.stderr)
        return 2
    facts = summary(doc)
    if args.json:
        print(json.dumps(facts, indent=2))
    else:
        print(f"decompose: {facts['source']['name']} ({facts['source']['bytes']} bytes) by {facts['handler']}; "
              f"rebuild {facts['rebuild']}; {facts['unparsed_bytes']} bytes kept as raw ranges; "
              f"{len(facts['content'])} content components; tree in {args.out}")
    return 0


def cmd_rebuild(args) -> int:
    from gather.decompose_rebuild import rebuild

    if bool(args.out) == bool(args.verify):
        print("rebuild: give --out FILE to rebuild, or --verify to check only", file=sys.stderr)
        return 2
    try:
        report = rebuild(args.tree, args.out, args.companion)
    except (OSError, ValueError) as exc:
        print(f"rebuild: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"rebuild: {report['bytes']} bytes, sha256 {report['sha256']}, "
              f"{'matches the original' if report['ok'] else 'DOES NOT match'}")
        for problem in report["problems"]:
            print(f"  {problem['node']} ({problem['kind']}): {problem['problem']}", file=sys.stderr)
    return 0 if report["ok"] else 1
