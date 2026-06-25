from __future__ import annotations

import argparse
import json
import sys
import time

from gather import __version__


def _split(s) -> list[str]:
    return [t.strip() for t in s.split(",") if t.strip()] if s else []


def _scope(args) -> list[str]:
    return _split(args.scope)


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


def _build_source(name: str, opts: dict):
    """Construct a source adapter by name (lazy imports keep the impure edges out of cold paths)."""
    if name == "web":
        from gather.web import WebSource
        return WebSource()
    if name == "feed":
        from gather.feed import FeedSource
        return FeedSource()
    if name == "docs":
        from gather.docs import DocsSource
        return DocsSource()
    if name == "arxiv":
        from gather.arxiv import ArxivSource
        return ArxivSource(max_results=int(opts.get("max_results", 10)))
    if name == "video":
        from gather.video import VideoSource
        return VideoSource(with_comments=bool(opts.get("comments", False)))
    if name == "pdf":
        from gather.pdf import PdfSource
        return PdfSource()
    raise ValueError(f"unknown source: {name!r}")


def _cmd_run(args) -> int:
    import time as _time

    from gather.derive import NullSynthesizer
    from gather.run import gather_run
    from gather.store import Corpus

    try:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
        job_specs = cfg.get("jobs", [])
        if not isinstance(job_specs, list) or not job_specs:
            raise ValueError("config needs a non-empty 'jobs' list")
        jobs = []
        for j in job_specs:
            if "source" not in j or "target" not in j:
                raise ValueError(f"each job needs 'source' and 'target': {j}")
            jobs.append((_build_source(j["source"], j), j["target"]))
        store = Corpus(cfg["store"]) if cfg.get("store") else None
        synthesizer = NullSynthesizer() if cfg.get("synthesize") else None
    except FileNotFoundError:
        print(f"run failed: config not found: {args.config}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"run failed: bad config: {exc}", file=sys.stderr)
        return 1
    try:
        record, _items = gather_run(
            jobs, clock=_time.time, scope=cfg.get("scope", []), store=store,
            synthesizer=synthesizer, synth_prompt=cfg.get("synth_prompt", ""),
        )
    except Exception as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"run: gathered {record.gathered}, kept {record.kept}, dropped {record.dropped}"
              f"{', +synthesis' if record.synthesized else ''}")
        print(f"digest seal: {record.digest_seal[:16]}... | record seal: {record.seal[:16]}...")
        if record.stored is not None:
            print(f"stored: {record.stored['added']} added, {record.stored['deduped']} deduped")
    return 0


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
    if args.action == "search":
        from gather.digest import digest, verify_digest
        from gather.recall import Query, recall
        from gather.source import Catalog

        q = Query(terms=tuple(_split(args.terms)), sources=tuple(_split(args.source)),
                  kinds=tuple(_split(args.kind)), methods=tuple(_split(args.method)))
        items = recall(c, q, limit=args.limit)
        d = digest(items)
        if args.json:
            cat = Catalog()
            cat.add(items)
            print(json.dumps({"catalog": cat.rows(), "digest": json.loads(d.to_json())},
                             indent=2, ensure_ascii=False))
        else:
            for i in items:
                print(f"  {i.kind:<10} {i.id:<20} {i.provenance.source:<8} {i.title[:36]}")
            print(f"{len(items)} match(es); digest seal {d.seal[:16]}... verified {verify_digest(d)}")
        return 0
    if args.action == "runs":
        history = list(c.runs())
        if args.verify:
            from gather.run import RunRecord, verify_record
            checked = [(r.get("digest_seal", "")[:12], verify_record(RunRecord.from_dict(r))) for r in history]
            bad = [s for s, ok in checked if not ok]
            if args.json:
                print(json.dumps([{"digest_seal": s, "verified": ok} for s, ok in checked], indent=2))
            else:
                for s, ok in checked:
                    print(f"  {'OK ' if ok else 'BAD'} record {s}")
                print(f"verified {len(checked)} run record(s), {len(bad)} bad")
            return 1 if bad else 0
        if args.json:
            print(json.dumps(history, indent=2, ensure_ascii=False))
        else:
            for r in history:
                syn = " +synthesis" if r.get("synthesized") else ""
                print(f"  gathered {r['gathered']:<4} kept {r['kept']:<4} scope {r.get('scope')}"
                      f" seal {r['digest_seal'][:12]}{syn}")
            print(f"{len(history)} run(s) in {args.dir}")
        return 0
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

    run = sub.add_parser("run", help="run a multi-source gather session from a JSON config")
    run.add_argument("config", help="path to a JSON config: {jobs:[{source,target}], scope, store, synthesize}")
    run.add_argument("--json", action="store_true", help="emit the witnessed run record as JSON")
    run.set_defaults(func=_cmd_run)

    corpus = sub.add_parser("corpus", help="inspect a stored corpus: list, verify, digest, or runs")
    corpus.add_argument("action", choices=["list", "verify", "digest", "runs", "search"])
    corpus.add_argument("dir", help="the corpus directory (created by --store)")
    corpus.add_argument("--json", action="store_true", help="emit as JSON")
    corpus.add_argument("--verify", action="store_true", help="with runs: re-check each record's seal")
    corpus.add_argument("--terms", default=None, help="with search: scope keywords (match title+body)")
    corpus.add_argument("--source", default=None, help="with search: filter to these sources (comma-sep)")
    corpus.add_argument("--kind", default=None, help="with search: filter to these kinds (comma-sep)")
    corpus.add_argument("--method", default=None, help="with search: filter to these methods (comma-sep)")
    corpus.add_argument("--limit", type=int, default=None, help="with search: cap the number of matches")
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
