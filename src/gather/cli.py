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


def _fetch_and_emit(fetch, args, fail: str = "fetch failed") -> int:
    try:
        items = fetch()
    except Exception as exc:
        print(f"{fail}: {exc}", file=sys.stderr)
        return 1
    return _emit(items, _scope(args), args.json)


def _cmd_video(args) -> int:
    from gather.video import VideoSource
    return _fetch_and_emit(lambda: VideoSource(with_comments=args.comments).fetch(args.url), args)


def _cmd_web(args) -> int:
    from gather.web import WebSource
    return _fetch_and_emit(lambda: WebSource().fetch(args.url), args)


def _cmd_feed(args) -> int:
    from gather.feed import FeedSource
    return _fetch_and_emit(lambda: FeedSource().fetch(args.url), args)


def _cmd_docs(args) -> int:
    from gather.docs import DocsSource
    return _fetch_and_emit(lambda: DocsSource().fetch(args.path), args, fail="read failed")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scope", default=None, help="comma-separated scope terms; keep items mentioning any")
    p.add_argument("--json", action="store_true", help="emit the catalog and digest as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gather", description="Gather: accountable research intake.")
    parser.add_argument("--version", action="version", version=f"gather {__version__}")
    sub = parser.add_subparsers(dest="command")

    parse = sub.add_parser("parse", help="parse a saved yt-dlp info.json (+ optional .vtt), offline, no network")
    parse.add_argument("info", help="path to a yt-dlp info.json")
    parse.add_argument("--vtt", default=None, help="path to a .vtt captions file")
    parse.add_argument("--auto-captions", action="store_true",
                       help="captions are machine-generated: collapse rolling-window growth, stamp auto-caption")
    _add_common(parse)
    parse.set_defaults(func=_cmd_parse)

    video = sub.add_parser("video", help="fetch a video via yt-dlp (needs yt-dlp on PATH and network)")
    video.add_argument("url")
    video.add_argument("--comments", action="store_true", help="also gather comments")
    _add_common(video)
    video.set_defaults(func=_cmd_video)

    web = sub.add_parser("web", help="fetch a static web page via http(s) and extract readable text")
    web.add_argument("url")
    _add_common(web)
    web.set_defaults(func=_cmd_web)

    feed = sub.add_parser("feed", help="fetch an RSS or Atom feed via http(s)")
    feed.add_argument("url")
    _add_common(feed)
    feed.set_defaults(func=_cmd_feed)

    docs = sub.add_parser("docs", help="read a local text file or a directory of them, offline")
    docs.add_argument("path")
    _add_common(docs)
    docs.set_defaults(func=_cmd_docs)

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
