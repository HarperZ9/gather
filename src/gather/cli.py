from __future__ import annotations

import argparse
import json
import sys
import time

from gather import __version__


def _scope(args) -> list[str]:
    return [t.strip() for t in args.scope.split(",") if t.strip()] if args.scope else []


def _emit(items, scope, as_json, store=None) -> int:
    from gather.digest import digest, verify_digest
    from gather.scope import filter_scope
    from gather.source import Catalog

    kept, dropped = filter_scope(items, scope)
    d = digest(kept)
    stored = None
    if store:
        from gather.store import Corpus
        stored = Corpus(store).add(kept)
    if as_json:
        cat = Catalog()
        cat.add(kept)
        out = {"catalog": cat.rows(), "digest": json.loads(d.to_json()), "dropped": dropped}
        if stored is not None:
            out["stored"] = stored
        print(json.dumps(out, indent=2, ensure_ascii=False))
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
    if stored is not None:
        print(f"stored to {store}: {stored['added']} added, {stored['deduped']} deduped")
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
    return _emit(items, _scope(args), args.json, store=args.store)


def _fetch_and_emit(fetch, args, fail: str = "fetch failed") -> int:
    try:
        items = fetch()
    except Exception as exc:
        print(f"{fail}: {exc}", file=sys.stderr)
        return 1
    return _emit(items, _scope(args), args.json, store=args.store)


def _cmd_corpus(args) -> int:
    from gather.digest import verify_digest
    from gather.store import Corpus

    c = Corpus(args.dir)
    if args.action == "list":
        rows = list(c.rows())
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for r in rows:
                print(f"  {r['kind']:<10} {r['id']:<20} {r['method']:<16} {r['title'][:40]}")
            print(f"{len(rows)} item(s) in {args.dir}")
        return 0
    if args.action == "verify":
        results = c.verify()
        bad = [r for r in results if r["status"] != "MATCH"]
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            counts: dict[str, int] = {}
            for r in results:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            print(f"verified {len(results)} item(s): {dict(sorted(counts.items()))}")
            for r in bad:
                print(f"  {r['status']:<8} {r['id']} {r['sha256'][:12]}")
        return 1 if bad else 0
    d = c.digest()  # action == "digest"
    if args.json:
        print(d.to_json())
    else:
        print(f"corpus digest: {len(d.receipts)} receipts, seal {d.seal[:16]}..., verified {verify_digest(d)}")
    return 0


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


def _cmd_arxiv(args) -> int:
    from gather.arxiv import ArxivSource
    return _fetch_and_emit(lambda: ArxivSource(max_results=args.max_results).fetch(args.query), args)


def _cmd_pdf(args) -> int:
    from gather.pdf import PdfSource
    return _fetch_and_emit(lambda: PdfSource().fetch(args.path), args, fail="read failed")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scope", default=None, help="comma-separated scope terms; keep items mentioning any")
    p.add_argument("--json", action="store_true", help="emit the catalog and digest as JSON")
    p.add_argument("--store", default=None, metavar="DIR", help="persist gathered items into a corpus at DIR")


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

    arxiv = sub.add_parser("arxiv", help="fetch papers from the arXiv API by id or free-text query")
    arxiv.add_argument("query", help="an arXiv id (2301.12345) or a search query")
    arxiv.add_argument("--max-results", type=int, default=10, help="max results for a search query")
    _add_common(arxiv)
    arxiv.set_defaults(func=_cmd_arxiv)

    pdf = sub.add_parser("pdf", help="extract text from a local PDF (needs pdftotext on PATH)")
    pdf.add_argument("path")
    _add_common(pdf)
    pdf.set_defaults(func=_cmd_pdf)

    corpus = sub.add_parser("corpus", help="inspect a stored corpus: list, verify, or digest it")
    corpus.add_argument("action", choices=["list", "verify", "digest"])
    corpus.add_argument("dir", help="the corpus directory (created by --store)")
    corpus.add_argument("--json", action="store_true", help="emit as JSON")
    corpus.set_defaults(func=_cmd_corpus)

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
