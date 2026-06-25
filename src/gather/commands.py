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
    if name == "api":
        from gather.api import ApiSource
        return ApiSource(
            auth_env=opts.get("auth_env", "GATHER_API_TOKEN"),
            items_key=opts.get("items_key"), id_key=opts.get("id_key", "id"),
            title_key=opts.get("title_key", "title"), text_key=opts.get("text_key"),
        )
    if name == "browser":
        from gather.browser import BrowserSource
        return BrowserSource()
    if name == "ocr":
        from gather.ocr import OcrSource
        return OcrSource()
    if name == "transcribe":
        from gather.transcribe import TranscribeSource
        return TranscribeSource()
    raise ValueError(f"unknown source: {name!r}")


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
    from gather.derive import NullSynthesizer, Synthesizer
    from gather.run import gather_run
    from gather.store import Corpus

    synthesizer: Synthesizer | None

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
        scope = cfg.get("scope", [])
        if not isinstance(scope, list):
            raise ValueError("'scope' must be a list of strings")  # a bare string would become char terms
        store = Corpus(cfg["store"]) if cfg.get("store") else None
        synth_cmd = cfg.get("synthesizer")  # a command list -> the real model edge
        if synth_cmd:
            if not isinstance(synth_cmd, list):
                raise ValueError("'synthesizer' must be a command list, e.g. [\"llm\", \"-m\", \"model\"]")
            from gather.model import SubprocessSynthesizer
            synthesizer = SubprocessSynthesizer(synth_cmd)
        elif cfg.get("synthesize"):
            synthesizer = NullSynthesizer()
        else:
            synthesizer = None
        prov_cmd = cfg.get("provenance")  # a command list -> compose an external origin verdict per item
        if prov_cmd is not None and not isinstance(prov_cmd, list):
            raise ValueError("'provenance' must be a command list, e.g. [\"python\", \"-m\", \"provenance\", \"check\"]")
        provider = None
        if prov_cmd:
            from gather.provenance import SubprocessProvenanceProvider
            provider = SubprocessProvenanceProvider(prov_cmd)
    except FileNotFoundError:
        print(f"run failed: config not found: {args.config}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"run failed: bad config: {exc}", file=sys.stderr)
        return 1
    try:
        record, _items = gather_run(
            jobs, clock=time.time, scope=scope, store=store,
            synthesizer=synthesizer, synth_prompt=cfg.get("synth_prompt", ""), provenance=provider,
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


# cmd_corpus lives in gather.corpus_cmd (the corpus inspection commands are their own module so no
# file exceeds the size budget); it is re-exported via cli.py's import.
