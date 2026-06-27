from __future__ import annotations

import json
import sys
import time


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


def _fetch_and_emit(fetch, args, fail: str = "fetch failed") -> int:
    try:
        items = fetch()
    except Exception as exc:
        print(f"{fail}: {exc}", file=sys.stderr)
        return 1
    return _emit(items, _scope(args), args.json, store=args.store)


def cmd_parse(args) -> int:
    from gather.video import parse_video

    with open(args.info, encoding="utf-8") as f:
        info_json = f.read()
    vtt = None
    if args.vtt:
        with open(args.vtt, encoding="utf-8") as f:
            vtt = f.read()
    items = parse_video(info_json, vtt, fetched_at=time.time(), auto_captions=args.auto_captions)
    return _emit(items, _scope(args), args.json, store=args.store)


def cmd_video(args) -> int:
    from gather.video import VideoSource
    return _fetch_and_emit(lambda: VideoSource(with_comments=args.comments).fetch(args.url), args)


def cmd_web(args) -> int:
    from gather.web import WebSource
    return _fetch_and_emit(lambda: WebSource().fetch(args.url), args)


def cmd_feed(args) -> int:
    from gather.feed import FeedSource
    return _fetch_and_emit(lambda: FeedSource().fetch(args.url), args)


def cmd_docs(args) -> int:
    from gather.docs import DocsSource
    return _fetch_and_emit(lambda: DocsSource().fetch(args.path), args, fail="read failed")


def cmd_arxiv(args) -> int:
    from gather.arxiv import ArxivSource
    return _fetch_and_emit(lambda: ArxivSource(max_results=args.max_results).fetch(args.query), args)


def cmd_pdf(args) -> int:
    from gather.pdf import PdfSource
    return _fetch_and_emit(lambda: PdfSource().fetch(args.path), args, fail="read failed")


def cmd_api(args) -> int:
    from gather.api import ApiSource
    return _fetch_and_emit(
        lambda: ApiSource(auth_env=args.auth_env, items_key=args.items_key, text_key=args.text_key,
                          id_key=args.id_key, title_key=args.title_key).fetch(args.url), args)


def cmd_browser(args) -> int:
    from gather.browser import BrowserSource
    return _fetch_and_emit(
        lambda: BrowserSource(browser=args.browser, no_sandbox=args.no_sandbox).fetch(args.url), args)


def cmd_ocr(args) -> int:
    from gather.ocr import OcrSource
    return _fetch_and_emit(lambda: OcrSource(lang=args.lang).fetch(args.path), args, fail="ocr failed")


def cmd_transcribe(args) -> int:
    from gather.transcribe import TranscribeSource
    return _fetch_and_emit(lambda: TranscribeSource(model=args.model).fetch(args.path), args,
                           fail="transcribe failed")


def cmd_run(args) -> int:
    from gather.run_config import load_run_config, plan_from_config, run_plan

    try:
        cfg = load_run_config(args.config)
        plan = plan_from_config(cfg)
    except FileNotFoundError:
        print(f"run failed: config not found: {args.config}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"run failed: bad config: {exc}", file=sys.stderr)
        return 1
    try:
        record, _items = run_plan(plan, clock=time.time)
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


# cmd_corpus lives in gather.corpus_cmd (the corpus inspection commands are their own module so no
# file exceeds the size budget); it is re-exported via cli.py's import.
