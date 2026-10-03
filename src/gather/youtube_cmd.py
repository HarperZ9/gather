"""CLI glue for YouTube intake: ``gather video``, ``gather parse`` and ``gather video-probe``.

``gather video URL`` reads through yt-dlp. When yt-dlp is throttled or failing and the user has
set their own Data API key (``GATHER_YOUTUBE_API_KEY``, or the variable named by
``--api-key-env``), the metadata comes from the official Data API instead, and the item's route
record says so. ``--no-api-fallback`` keeps every read on yt-dlp.

``gather video-probe`` measures the yt-dlp path on a fixed set of three public videos and prints
a verdict: ``ok``, ``throttled`` or ``failing``. Exit status 0 for ``ok``, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable

from gather.youtube_api import KEY_ENV


def add_video_parsers(sub, add_common: Callable) -> None:
    from gather.commands import cmd_parse, cmd_video
    from gather.video_cmd import add_ytdlp_options

    parse = sub.add_parser("parse", help="parse a saved yt-dlp info.json (+ optional .vtt), offline, no network")
    parse.add_argument("info", help="path to a yt-dlp info.json")
    parse.add_argument("--vtt", default=None, help="path to a .vtt captions file")
    parse.add_argument("--auto-captions", action="store_true",
                       help="captions are machine-generated: collapse rolling-window growth, stamp auto-caption")
    add_common(parse)
    parse.set_defaults(func=cmd_parse)

    video = sub.add_parser("video", help="fetch a video via yt-dlp, with the Data API as a keyed fallback")
    video.add_argument("url")
    video.add_argument("--comments", action="store_true", help="also gather comments")
    add_ytdlp_options(video)
    video.add_argument("--api-key-env", default=KEY_ENV, metavar="NAME",
                       help=f"environment variable holding your own Data API key (default {KEY_ENV}); "
                            "used only when yt-dlp is throttled or failing")
    video.add_argument("--no-api-fallback", action="store_true",
                       help="never fall back to the Data API; every read stays on yt-dlp")
    add_common(video)
    video.set_defaults(func=cmd_video)

    probe = sub.add_parser("video-probe", help="measure the yt-dlp path on three fixed public videos")
    probe.add_argument("--gap", type=float, default=None, metavar="S",
                       help="seconds between probe videos (2 or more)")
    probe.add_argument("--timeout", type=float, default=60.0, metavar="S", help="seconds per yt-dlp call")
    probe.add_argument("--js-runtime", default="auto", help="yt-dlp --js-runtimes: auto, none, or RUNTIME[:PATH]")
    probe.add_argument("--yt-dlp", dest="yt_dlp", default="yt-dlp", help="the yt-dlp executable")
    probe.add_argument("--json", action="store_true", help="emit the probe report as JSON")
    probe.set_defaults(func=cmd_video_probe)


def route_from_args(args, *, with_comments: bool):
    """The ``YouTubeRoute`` for ``gather video``: yt-dlp with the options given, plus the Data API
    fallback unless ``--no-api-fallback`` is set."""
    from gather.video_cmd import video_source_from_args
    from gather.youtube_api import DataApiClient
    from gather.youtube_route import YouTubeRoute

    api = None if getattr(args, "no_api_fallback", False) else DataApiClient(
        key_env=getattr(args, "api_key_env", KEY_ENV))
    return YouTubeRoute(
        source_factory=lambda runner: video_source_from_args(args, with_comments=with_comments, runner=runner),
        api=api)


def cmd_video_probe(args) -> int:
    from gather.video_source import VideoSource
    from gather.youtube_probe import MIN_GAP_S, run_probe
    from gather.youtube_route import TimedRunner

    try:
        timed = TimedRunner()
        src = VideoSource(yt_dlp=args.yt_dlp, js_runtime=args.js_runtime, timeout=args.timeout, runner=timed)
        report = run_probe(timed, src.gather, gap_s=MIN_GAP_S if args.gap is None else args.gap)
    except ValueError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"yt-dlp probe: {report['verdict']} ({report['reason']})")
        for row in report["videos"]:
            print(f"  {row['video']}  metadata {row['metadata_s']}s  caption {row['caption']} "
                  f"{row['caption_bytes']} B in {row['caption_s']}s  {row['error_code'] or ''}".rstrip())
        print(f"median metadata call: {report['median_metadata_s']}s; "
              f"{report['metadata_calls_per_min']} calls/min")
    return 0 if report["verdict"] == "ok" else 1
