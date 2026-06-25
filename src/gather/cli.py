from __future__ import annotations

import argparse
import json
import sys
import time

from gather import __version__


def _scope(args) -> list[str]:
    return [t.strip() for t in args.scope.split(",") if t.strip()] if args.scope else []


def _emit(items, scope, as_json) -> int:
    from gather.digest import digest, verify_digest
    from gather.scope import filter_scope
    from gather.source import Catalog

    kept, dropped = filter_scope(items, scope)
    d = digest(kept)
    if as_json:
        cat = Catalog()
        cat.add(kept)
        print(json.dumps(
            {"catalog": cat.rows(), "digest": json.loads(d.to_json()), "dropped": dropped},
            indent=2, ensure_ascii=False,
        ))
        return 0
    note = f", dropped {dropped} out of scope" if scope else ""
    print(f"gathered {len(kept)} item(s){note}")
    by_kind: dict[str, int] = {}
    for i in kept:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
    print("by kind:", dict(sorted(by_kind.items())))
    for i in kept:
        print(f"  {i.kind:<10} {i.id:<16} {i.title[:50]}")
    print(f"digest seal: {d.seal[:16]}... | verified: {verify_digest(d)}")
    return 0


def _cmd_parse(args) -> int:
    from gather.video import parse_video

    with open(args.info, encoding="utf-8") as f:
        info_json = f.read()
    vtt = None
    if args.vtt:
        with open(args.vtt, encoding="utf-8") as f:
            vtt = f.read()
    items = parse_video(info_json, vtt, fetched_at=time.time(), auto_captions=args.auto_captions)
    return _emit(items, _scope(args), args.json)


def _cmd_video(args) -> int:
    from gather.video import VideoSource

    try:
        items = VideoSource(with_comments=args.comments).fetch(args.url)
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    return _emit(items, _scope(args), args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gather", description="Gather: accountable research intake.")
    parser.add_argument("--version", action="version", version=f"gather {__version__}")
    sub = parser.add_subparsers(dest="command")

    parse = sub.add_parser("parse", help="parse a saved yt-dlp info.json (+ optional .vtt), offline, no network")
    parse.add_argument("info", help="path to a yt-dlp info.json")
    parse.add_argument("--vtt", default=None, help="path to a .vtt captions file")
    parse.add_argument("--auto-captions", action="store_true",
                       help="captions are machine-generated: collapse rolling-window growth, stamp auto-caption")
    parse.add_argument("--scope", default=None, help="comma-separated scope terms; keep items mentioning any")
    parse.add_argument("--json", action="store_true", help="emit the catalog and digest as JSON")
    parse.set_defaults(func=_cmd_parse)

    video = sub.add_parser("video", help="fetch a video via yt-dlp (needs yt-dlp on PATH and network)")
    video.add_argument("url")
    video.add_argument("--comments", action="store_true", help="also gather comments")
    video.add_argument("--scope", default=None, help="comma-separated scope terms")
    video.add_argument("--json", action="store_true", help="emit the catalog and digest as JSON")
    video.set_defaults(func=_cmd_video)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
