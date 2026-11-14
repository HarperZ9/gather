"""CLI glue for ``gather video-bundle`` and ``gather comment-balance``.

``gather video-bundle URL --out DIR`` saves one video as a bundle folder (``gather.video_bundle``):
captions and both transcripts, chapters and metadata, up to ``--max-comments`` comments with
replies (600 by default, sorted by top), the balanced comment synthesis, SOURCE.txt and
SHA256SUMS. ``--media`` adds the media file, a local research copy that is never uploaded.

``gather comment-balance PATH`` runs the balanced synthesis offline on a bundle's thread file, a
CMMNS thread file, or a yt-dlp info.json with comments, and prints Markdown (or ``--json``).

Exit status: 0 on success; 1 when the fetch failed, YouTube asked for a bot check, or the media
file was asked for and not saved; 2 on bad options or an unreadable file.
"""

from __future__ import annotations

import argparse
import json
import sys


def add_bundle_parsers(sub) -> None:
    from gather.video_cmd import add_ytdlp_options

    p = sub.add_parser("video-bundle", help="save a video as a bundle: captions, transcript, chapters, comments, balance, hashes")
    p.add_argument("url")
    p.add_argument("--out", required=True, metavar="DIR", help="the bundle folder to write")
    p.add_argument("--media", action="store_true", help="also save the media file (a local research copy, never uploaded)")
    p.add_argument("--max-comments", type=int, default=600, metavar="N", help="comments to read, sorted by top (0 for none)")
    p.add_argument("--no-balance", action="store_true", help="skip the balanced comment synthesis")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--fast", action="store_true",
                   help="read captions and frames while the comments are still being read, keep requests "
                        "1 s apart, and cap replies so the comment budget goes to top-level comments")
    p.add_argument("--frames", action=argparse.BooleanOptionalAction, default=True,
                   help="contact sheets of frames across the video, cut from the site's preview storyboard "
                        "(no video download; needs Pillow)")
    p.add_argument("--max-replies", type=int, default=None, metavar="N",
                   help="replies to read in all, at most 5 to a thread (default: every reply, or a tenth of "
                        "--max-comments with --fast)")
    add_ytdlp_options(p)
    p.set_defaults(func=cmd_video_bundle)

    b = sub.add_parser("comment-balance", help="balanced synthesis of a video's comments, offline, from a saved file")
    b.add_argument("path", help="a bundle's <id>.thread.json, a CMMNS .thread.json, or a yt-dlp info.json with comments")
    b.add_argument("--json", action="store_true", help="print the gather.comment-balance/1 record")
    b.add_argument("--max-claims", type=int, default=20, metavar="N")
    b.set_defaults(func=cmd_comment_balance)


def comments_from_file(doc: dict) -> tuple[list[dict], str, str]:
    """Flat comment records, the title and the address from any of the three file shapes."""
    from gather.comment_balance import flatten

    if isinstance(doc.get("comments"), list) and str(doc.get("format", "")).startswith("cmmns.capture-thread"):
        flat = flatten(doc["comments"])
        for c in flat:
            c["like_count"] = c.get("score") if isinstance(c.get("score"), int) else 0
            c["author_is_uploader"] = "channel owner" in str(c.get("flair") or "")
        return flat, "", str((doc.get("post") or {}).get("url") or "")
    if str(doc.get("format", "")).startswith("gather.video-thread"):
        return flatten(doc.get("comments") or []), "", str(doc.get("url") or "")
    if isinstance(doc.get("comments"), list):
        return list(doc["comments"]), str(doc.get("title") or ""), str(doc.get("webpage_url") or "")
    raise ValueError("no comments in this file")


def cmd_comment_balance(args) -> int:
    from gather.comment_balance import balance
    from gather.comment_report import report_markdown

    try:
        with open(args.path, encoding="utf-8") as f:
            doc = json.load(f)
        comments, title, url = comments_from_file(doc)
    except (OSError, ValueError) as exc:
        print(f"comment-balance: {exc}", file=sys.stderr)
        return 2
    rec = balance(comments, title=title, url=url, max_claims=args.max_claims)
    print(json.dumps(rec, indent=2, ensure_ascii=False) if args.json else report_markdown(rec))
    return 0


FAST_SPACING = 1.0
REPLIES_PER_THREAD = 5


def comment_args(max_comments: int, max_replies: int | None, *, fast: bool) -> str:
    """The yt-dlp extractor arguments for the comment read: sorted by top (the order the site
    serves first, so it costs no extra request) and capped at ``max_comments``. Every thread
    with replies costs one more request, so ``fast`` gives replies a tenth of the budget, at
    most ``REPLIES_PER_THREAD`` to a thread, and the rest goes to top-level comments."""
    if max_replies is None and not fast:
        return f"youtube:max_comments={max_comments},all,all,all;comment_sort=top"
    replies = max_comments // 10 if max_replies is None else max_replies
    return f"youtube:max_comments={max_comments},all,{replies},{min(replies, REPLIES_PER_THREAD)};comment_sort=top"


def cmd_video_bundle(args) -> int:
    from gather.pacing import HostLimiter
    from gather.video_bundle_run import fetch_bundle
    from gather.video_cmd import video_source_from_args

    if args.max_comments < 0:
        print("video-bundle: --max-comments must be 0 or more", file=sys.stderr)
        return 2
    if args.max_replies is not None and args.max_replies < 0:
        print("video-bundle: --max-replies must be 0 or more", file=sys.stderr)
        return 2
    if args.fast:  # yt-dlp's own requests stay at least 1 s apart; a larger --sleep-requests is kept
        args.sleep_requests = max(FAST_SPACING, args.sleep_requests or 0.0)
    extra = (comment_args(args.max_comments, args.max_replies, fast=args.fast),) if args.max_comments else ()
    try:
        src = video_source_from_args(args, with_comments=args.max_comments > 0, extractor_args=extra)
    except ValueError as exc:
        print(f"video-bundle: {exc}", file=sys.stderr)
        return 2
    res = fetch_bundle(args.url, args.out, src, media=args.media, with_balance=not args.no_balance, fast=args.fast,
                       frames=args.frames, limiter=HostLimiter(max(FAST_SPACING, args.sleep_requests or 0.0)))
    report = {"ok": res.ok, "out": res.out_dir, "video": res.video_id, "files": res.files, "caption": res.caption,
              "comments": res.comments, "frames": res.frames, "media": res.media, "media_error": res.media_error,
              "error": res.error, "balance": (res.balance or {}).get("balance", {}).get("sentence"),
              "timings": res.timings}
    if args.json:
        print(json.dumps(report, indent=2))
    elif res.ok:
        print(f"bundle {res.video_id}: {len(res.files)} files in {res.out_dir}; captions {res.caption}; {res.comments} comments; "
              f"media {res.media or ('not saved: ' + res.media_error if res.media_error else 'not asked for')}")
        print(res.frames)
        if report["balance"]:
            print(f"balance: {report['balance']}")
    else:
        print(f"video-bundle failed: {res.error}", file=sys.stderr)
    return 0 if res.ok and not (args.media and not res.media) else 1
