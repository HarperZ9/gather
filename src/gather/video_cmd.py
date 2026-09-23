"""CLI glue for video intake: the shared yt-dlp options and the ``channel`` command.

``gather channel URL --store DIR`` lists a channel's videos, shorts, and streams tabs (or one
playlist), gathers each entry as one pass, and writes a run summary. Passes are separate so
the throttle-prone caption endpoint never blocks metadata and comments:

    gather channel URL --store corpus --no-captions --comments      # pass 1
    gather channel URL --store corpus --captions-only --concurrency 1 --interval 15 --jitter 5

Exit status: 0 when every pending entry was attempted; 1 when listing failed or the pass
stopped because an entry spent its whole backoff budget still throttled; 2 on bad options.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time

from gather.channel import TABS, ChannelRun, list_channel, tab_urls
from gather.channel_ledger import (
    DOES_NOT_PROVE,
    SUMMARY_SCHEMA,
    intake_dir,
    is_settled,
    latest_rows,
    ledger_path,
    pass_name,
    stored_refs,
    summarize,
    write_json,
)
from gather.pacing import BackoffPolicy, Pacer
from gather.video_source import VideoSource
from gather.ytdlp import DEFAULT_TIMEOUT

# Channel passes are long and unattended, so a throttle gets a generous, bounded wait.
CHANNEL_BACKOFF = BackoffPolicy(base=60.0, factor=2.0, cap=900.0, max_attempts=5, max_total_wait=2700.0)


def _split(s: str | None) -> list[str]:
    return [t.strip() for t in s.split(",") if t.strip()] if s else []


def add_ytdlp_options(p, *, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Options every yt-dlp-backed command shares: pass selection, JS runtime, pacing, backoff."""
    passes = p.add_mutually_exclusive_group()
    passes.add_argument("--no-captions", action="store_true",
                        help="skip captions: gather metadata (and comments) only")
    passes.add_argument("--captions-only", action="store_true",
                        help="gather captions only: store the transcript item, no metadata or comments")
    p.add_argument("--caption-langs", default="en", help="caption languages in preference order (comma-sep)")
    p.add_argument("--js-runtime", default="auto",
                   help="yt-dlp --js-runtimes: auto (node when on PATH), none, or RUNTIME[:PATH]")
    p.add_argument("--sleep-requests", type=float, default=None, metavar="S",
                   help="yt-dlp: seconds to sleep between requests during extraction")
    p.add_argument("--sleep-subtitles", type=float, default=None, metavar="S",
                   help="yt-dlp: seconds to sleep before each subtitle download")
    p.add_argument("--timeout", type=float, default=timeout, metavar="S", help="seconds per yt-dlp call")
    p.add_argument("--retries", type=int, default=None, metavar="N",
                   help="attempts per yt-dlp call while throttled (HTTP 429), counting the first")
    p.add_argument("--backoff-base", type=float, default=None, metavar="S", help="first backoff wait")
    p.add_argument("--backoff-cap", type=float, default=None, metavar="S", help="ceiling on one backoff wait")
    p.add_argument("--backoff-budget", type=float, default=None, metavar="S",
                   help="ceiling on the total backoff wait for one call")
    p.add_argument("--yt-dlp", dest="yt_dlp", default="yt-dlp", help="the yt-dlp executable")


def captions_mode(args) -> str:
    if getattr(args, "captions_only", False):
        return "only"
    return "skip" if getattr(args, "no_captions", False) else "with"


def backoff_from_args(args, default: BackoffPolicy) -> BackoffPolicy:
    changes = {name: value for name, value in (
        ("max_attempts", args.retries), ("base", args.backoff_base),
        ("cap", args.backoff_cap), ("max_total_wait", args.backoff_budget)) if value is not None}
    return dataclasses.replace(default, **changes)


def video_source_from_args(args, *, with_comments: bool, default_backoff: BackoffPolicy | None = None,
                           pacer: Pacer | None = None) -> VideoSource:
    from gather.video_source import DEFAULT_BACKOFF
    return VideoSource(
        yt_dlp=args.yt_dlp, with_comments=with_comments, timeout=args.timeout,
        captions=captions_mode(args), caption_langs=tuple(_split(args.caption_langs)) or ("en",),
        js_runtime=args.js_runtime, sleep_requests=args.sleep_requests,
        sleep_subtitles=args.sleep_subtitles,
        backoff=backoff_from_args(args, default_backoff or DEFAULT_BACKOFF), pacer=pacer,
    )


def add_channel_parser(sub) -> None:
    ch = sub.add_parser(
        "channel",
        help="gather every upload on a channel's videos/shorts/streams tabs (or a playlist) into a corpus")
    ch.add_argument("url", help="a channel URL (https://www.youtube.com/@name) or a playlist URL")
    ch.add_argument("--store", required=True, metavar="DIR", help="corpus directory; also holds the pass ledger")
    ch.add_argument("--tabs", default=",".join(TABS), help="channel tabs to list (comma-sep)")
    ch.add_argument("--comments", action="store_true", help="also gather comments")
    ch.add_argument("--concurrency", type=int, default=2, help="entries gathered at once (default 2)")
    ch.add_argument("--interval", type=float, default=2.0, metavar="S", help="minimum seconds between entry starts")
    ch.add_argument("--jitter", type=float, default=2.0, metavar="S", help="up to S random extra seconds per start")
    ch.add_argument("--max-throttled", type=int, default=1, metavar="N",
                    help="stop the pass after N entries spend their backoff budget still throttled")
    ch.add_argument("--limit", type=int, default=None, metavar="N", help="gather at most N pending entries")
    ch.add_argument("--summary", default=None, metavar="PATH",
                    help="summary JSON path (default <store>/intake/summary-<pass>.json)")
    ch.add_argument("--json", action="store_true", help="print the summary as JSON")
    add_ytdlp_options(ch, timeout=600.0)
    ch.set_defaults(func=cmd_channel)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _pending(entries: list[dict], store: str, pass_: str, ledger: str) -> tuple[list[dict], int]:
    from gather.store import Corpus
    latest = latest_rows(ledger)
    kind = {"captions": "transcript", "metadata": "metadata"}.get(pass_)
    stored = stored_refs(Corpus(store).rows(), kind) if kind else set()
    pending = [e for e in entries
               if e["id"] not in stored and not (e["id"] in latest and is_settled(latest[e["id"]], pass_))]
    return pending, len(entries) - len(pending)


def _settings(args, source: VideoSource, backoff: BackoffPolicy) -> dict:
    return {"tabs": _split(args.tabs), "captions": captions_mode(args), "comments": args.comments,
            "caption_langs": _split(args.caption_langs), "concurrency": args.concurrency,
            "interval_s": args.interval, "jitter_s": args.jitter, "timeout_s": args.timeout,
            "sleep_requests_s": args.sleep_requests, "sleep_subtitles_s": args.sleep_subtitles,
            "max_throttled": args.max_throttled, "limit": args.limit, "backoff": backoff.to_dict(),
            "yt_dlp_argv_prefix": source.base_argv}


def cmd_channel(args) -> int:
    from gather.store import Corpus
    try:
        tabs = _split(args.tabs)
        tab_urls(args.url, tabs)
        backoff = backoff_from_args(args, CHANNEL_BACKOFF)
        pacer = Pacer(args.interval, args.jitter)
        source = video_source_from_args(args, with_comments=args.comments, default_backoff=backoff, pacer=pacer)
        run_pass = pass_name(captions_mode(args), args.comments)
        run = ChannelRun(source, Corpus(args.store), ledger_path(args.store, run_pass), run_pass, pacer,
                         concurrency=args.concurrency, max_throttled=args.max_throttled, log=_err)
    except ValueError as exc:
        _err(f"channel failed: {exc}")
        return 2
    started = time.time()
    listing = list_channel(source, args.url, tabs)
    write_json(os.path.join(intake_dir(args.store), "listing.json"),
               {"target": args.url, "listed_at": started, **listing})
    tabs_report = {t: {k: v for k, v in info.items() if k != "url"} for t, info in listing["tabs"].items()}
    if not listing["entries"] and any("error" in info for info in listing["tabs"].values()):
        _err(f"channel failed: nothing listed: {json.dumps(tabs_report)}")
        return 1
    pending, settled = _pending(listing["entries"], args.store, run_pass, run.ledger)
    if args.limit is not None:
        pending = pending[:max(0, args.limit)]
    _err(f"gather channel: pass {run_pass}: {listing['unique_entries']} listed, {settled} settled, "
         f"{len(pending)} to gather")
    rows = run.run(pending)
    latest = latest_rows(run.ledger)
    ids = [e["id"] for e in listing["entries"]]
    totals = summarize(latest[i] for i in ids if i in latest)
    totals["without_ledger_row"] = sum(1 for i in ids if i not in latest)
    summary_path = args.summary or os.path.join(intake_dir(args.store), f"summary-{run_pass}.json")
    summary = {
        "schema": SUMMARY_SCHEMA, "target": args.url, "pass": run_pass,
        "started_at": round(started, 3), "finished_at": round(time.time(), 3),
        "settings": _settings(args, source, backoff),
        "listing": {"tabs": tabs_report, "unique_entries": listing["unique_entries"],
                    "duplicates": listing["duplicates"]},
        "resume": {"settled_before_run": settled, "gathered_this_run": len(pending)},
        "stopped": run.stop_reason, "stored_this_run": run.stored,
        "run": summarize(rows), "pass_totals": totals,
        "files": {"ledger": run.ledger, "summary": summary_path,
                  "listing": os.path.join(intake_dir(args.store), "listing.json")},
        "does_not_prove": list(DOES_NOT_PROVE),
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else _human(summary))
    return 1 if run.stop_reason else 0


def _human(s: dict) -> str:
    tabs = ", ".join(f"{t} {i['listed']}" + (f" ({i.get('code')})" if i.get("error") else "")
                     for t, i in s["listing"]["tabs"].items())
    lines = [f"channel {s['target']} pass={s['pass']}",
             f"listed: {tabs}; unique {s['listing']['unique_entries']}"]
    for label, part in (("this run", s["run"]), ("pass totals", s["pass_totals"])):
        c, m = part["captions"], part["comments"]
        lines.append(f"{label}: {part['entries']} entries {part['status']}; captions manual {c['manual']}, "
                     f"auto {c['auto']}, missing {c['missing']} {c['missing_by_reason']}; comments {m['total']}; "
                     f"failures {part['failures_by_reason']}; retries {part['retries']['total']}")
    if s["stopped"]:
        lines.append(f"STOPPED: {s['stopped']}")
    lines.append(f"stored: {s['stored_this_run']['added']} added, {s['stored_this_run']['deduped']} deduped")
    lines.append(f"summary: {s['files']['summary']}")
    return "\n".join(lines)
