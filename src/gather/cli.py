from __future__ import annotations

import argparse
import sys

from gather import __version__
from gather.commands import (
    cmd_api,
    cmd_arxiv,
    cmd_browser,
    cmd_docs,
    cmd_feed,
    cmd_ocr,
    cmd_parse,
    cmd_pdf,
    cmd_run,
    cmd_transcribe,
    cmd_video,
    cmd_web,
)
from gather.corpus_cmd import cmd_corpus
from gather.flagship import cmd_demo, cmd_doctor, cmd_status
from gather.mcp import serve as serve_mcp


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scope", default=None, help="comma-separated scope terms; keep items mentioning any")
    p.add_argument("--json", action="store_true", help="emit the catalog and digest as JSON")
    p.add_argument("--store", default=None, metavar="DIR", help="persist gathered items into a corpus at DIR")


def _add_flagship_commands(sub) -> None:
    status = sub.add_parser("status", help="emit Gather's Project Telos operator-spine status")
    status.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser("doctor", help="check Gather's operator-spine readiness")
    doctor.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    doctor.set_defaults(func=cmd_doctor)

    demo = sub.add_parser("demo", help="show Gather's operator-spine demo command")
    demo.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    demo.set_defaults(func=cmd_demo)


def _add_corpus_parser(sub) -> None:
    corpus = sub.add_parser(
        "corpus", help="inspect a stored corpus: list/verify/digest/runs/search/stats/prune/availability")
    corpus.add_argument("action",
                        choices=["list", "verify", "digest", "runs", "search", "stats", "prune", "availability"])
    corpus.add_argument("dir", help="the corpus directory (created by --store)")
    corpus.add_argument("--json", action="store_true", help="emit as JSON")
    corpus.add_argument("--verify", action="store_true", help="with runs: re-check each record's seal")
    corpus.add_argument("--apply", action="store_true", help="with prune: actually delete orphan objects")
    corpus.add_argument("--terms", default=None,
                        help="with search: scope keywords, case-insensitive substrings of title+body (any match)")
    corpus.add_argument("--source", default=None,
                        help="with search: keep items from any of these sources (comma-sep, OR within)")
    corpus.add_argument("--kind", default=None, help="with search: keep items of any of these kinds (comma-sep)")
    corpus.add_argument("--method", default=None, help="with search: keep items of any of these methods (comma-sep)")
    corpus.add_argument("--limit", type=int, default=None, help="with search: cap the matches (<=0 means none)")
    corpus.set_defaults(func=cmd_corpus)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gather", description="Gather: accountable research intake.")
    parser.add_argument("--version", action="version", version=f"gather {__version__}")
    sub = parser.add_subparsers(dest="command")
    _add_flagship_commands(sub)

    parse = sub.add_parser("parse", help="parse a saved yt-dlp info.json (+ optional .vtt), offline, no network")
    parse.add_argument("info", help="path to a yt-dlp info.json")
    parse.add_argument("--vtt", default=None, help="path to a .vtt captions file")
    parse.add_argument("--auto-captions", action="store_true",
                       help="captions are machine-generated: collapse rolling-window growth, stamp auto-caption")
    _add_common(parse)
    parse.set_defaults(func=cmd_parse)

    video = sub.add_parser("video", help="fetch a video via yt-dlp (needs yt-dlp on PATH and network)")
    video.add_argument("url")
    video.add_argument("--comments", action="store_true", help="also gather comments")
    _add_common(video)
    video.set_defaults(func=cmd_video)

    web = sub.add_parser("web", help="fetch a static web page via http(s) and extract readable text")
    web.add_argument("url")
    _add_common(web)
    web.set_defaults(func=cmd_web)

    feed = sub.add_parser("feed", help="fetch an RSS or Atom feed via http(s)")
    feed.add_argument("url")
    _add_common(feed)
    feed.set_defaults(func=cmd_feed)

    docs = sub.add_parser("docs", help="read a local text file or a directory of them, offline")
    docs.add_argument("path")
    _add_common(docs)
    docs.set_defaults(func=cmd_docs)

    arxiv = sub.add_parser("arxiv", help="fetch papers from the arXiv API by id or free-text query")
    arxiv.add_argument("query", help="an arXiv id (2301.12345) or a search query")
    arxiv.add_argument("--max-results", type=int, default=10, help="max results for a search query")
    _add_common(arxiv)
    arxiv.set_defaults(func=cmd_arxiv)

    pdf = sub.add_parser("pdf", help="extract text from a local PDF (needs pdftotext on PATH)")
    pdf.add_argument("path")
    _add_common(pdf)
    pdf.set_defaults(func=cmd_pdf)

    api = sub.add_parser("api", help="fetch a JSON API with a bearer token from the environment")
    api.add_argument("url")
    api.add_argument("--auth-env", default="GATHER_API_TOKEN", help="env var holding the bearer token")
    api.add_argument("--items-key", default=None, help="key of the records array in the JSON response")
    api.add_argument("--text-key", default=None, help="record field to use as item text (else the whole record)")
    api.add_argument("--id-key", default="id", help="record field to use as item id")
    api.add_argument("--title-key", default="title", help="record field to use as item title")
    _add_common(api)
    api.set_defaults(func=cmd_api)

    browser = sub.add_parser("browser", help="fetch a JS-rendered page via a headless browser (needs chromium on PATH)")
    browser.add_argument("url")
    browser.add_argument("--browser", default="chromium", help="headless browser binary")
    browser.add_argument("--no-sandbox", action="store_true",
                         help="disable the Chromium sandbox (only if running as root in a container; a downgrade)")
    _add_common(browser)
    browser.set_defaults(func=cmd_browser)

    ocr = sub.add_parser("ocr", help="recognize text in a local image via tesseract (needs tesseract on PATH)")
    ocr.add_argument("path")
    ocr.add_argument("--lang", default="eng", help="tesseract language code")
    _add_common(ocr)
    ocr.set_defaults(func=cmd_ocr)

    transcribe = sub.add_parser("transcribe", help="transcribe a local audio file via whisper (needs whisper on PATH)")
    transcribe.add_argument("path")
    transcribe.add_argument("--model", default="base", help="whisper model name")
    _add_common(transcribe)
    transcribe.set_defaults(func=cmd_transcribe)

    run = sub.add_parser("run", help="run a multi-source gather session from a JSON config")
    run.add_argument("config",
                     help="JSON config: {jobs:[{source,target}], scope, store, "
                          "synthesize | synthesizer:[cmd...], synth_prompt}")
    run.add_argument("--json", action="store_true", help="emit the witnessed run record as JSON")
    run.set_defaults(func=cmd_run)

    _add_corpus_parser(sub)

    mcp = sub.add_parser("mcp", help="serve Gather tools over MCP stdio")
    mcp.set_defaults(func=lambda _args: serve_mcp())

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
