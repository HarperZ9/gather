"""CLI glue for ``gather saves``.

``gather saves FOLDER --out DIR`` reads a folder of CMMNS saves (``daylight.sidecar/1`` Markdown
sidecars with their JSON sidecars and media files) and writes ``items``, ``entities`` and
``media`` as CSV and JSON Lines plus ``manifest.json`` (``gather.saves-tables/1``). The work is
done by fixed rules in ``gather.saves_tables``: no model, no network, no subprocess, and the same
folder gives the same bytes.

``gather saves --probe FILE`` prints the media row for one local file as JSON.

Exit status: 0 when the tables were written (per-file problems are listed in the manifest) or the
file was probed; 2 on bad options, an input that is not a folder, or a file that cannot be read.
"""

from __future__ import annotations

import json
import sys


def add_saves_parser(sub) -> None:
    p = sub.add_parser("saves", help="turn a folder of CMMNS saves into items, entities and media tables, offline")
    p.add_argument("folder", nargs="?", help="the folder of saves, read recursively")
    p.add_argument("--out", metavar="DIR", help="the folder to write the tables and manifest.json into")
    p.add_argument("--no-media-hash", action="store_true", help="leave the media sha256 column empty (faster on large folders)")
    p.add_argument("--probe", metavar="FILE", help="print the media row for one local file as JSON and stop")
    p.add_argument("--json", action="store_true", help="print the manifest as JSON")
    p.set_defaults(func=cmd_saves)


def _probe(path: str, with_hash: bool) -> int:
    from gather.media_probe import probe

    try:
        row, note = probe(path, with_hash)
    except OSError as exc:
        print(f"saves: cannot read the file: {exc.strerror or type(exc).__name__}", file=sys.stderr)
        return 2
    if note:
        print(f"saves: {note}", file=sys.stderr)
    print(json.dumps({"path": path.replace("\\", "/"), "item_id": "", "listed": False, **row}, indent=2))
    return 0


def cmd_saves(args) -> int:
    from gather.saves_tables import build_tables

    if args.probe:
        if args.folder or args.out:
            print("saves: --probe takes one file and no folder or --out", file=sys.stderr)
            return 2
        return _probe(args.probe, not args.no_media_hash)
    if not args.folder or not args.out:
        print("saves: give a folder and --out DIR, or --probe FILE", file=sys.stderr)
        return 2
    try:
        manifest = build_tables(args.folder, args.out, media_hash=not args.no_media_hash)
    except (OSError, ValueError) as exc:
        print(f"saves: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0
    rows = {name: table["rows"] for name, table in manifest["tables"].items() if name.endswith(".csv")}
    print(f"saves: {manifest['input_items']} items, {rows['entities.csv']} entities, {rows['media.csv']} media files; "
          f"{manifest['skipped_markdown']} other Markdown files skipped; {len(manifest['problems'])} problems; "
          f"tables in {args.out}")
    return 0
