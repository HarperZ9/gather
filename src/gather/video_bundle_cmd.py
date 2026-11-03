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


def cmd_video_bundle(args) -> int:
    from gather.video_bundle_run import fetch_bundle
    from gather.video_cmd import video_source_from_args

    if args.max_comments < 0:
        print("video-bundle: --max-comments must be 0 or more", file=sys.stderr)
        return 2
    extra = (f"youtube:max_comments={args.max_comments},all,all,all;comment_sort=top",) if args.max_comments else ()
    try:
        src = video_source_from_args(args, with_comments=args.max_comments > 0, extractor_args=extra)
    except ValueError as exc:
        print(f"video-bundle: {exc}", file=sys.stderr)
        return 2
    res = fetch_bundle(args.url, args.out, src, media=args.media, with_balance=not args.no_balance)
    report = {"ok": res.ok, "out": res.out_dir, "video": res.video_id, "files": res.files, "caption": res.caption,
              "comments": res.comments, "media": res.media, "media_error": res.media_error, "error": res.error,
              "balance": (res.balance or {}).get("balance", {}).get("sentence")}
    if args.json:
        print(json.dumps(report, indent=2))
    elif res.ok:
        print(f"bundle {res.video_id}: {len(res.files)} files in {res.out_dir}; captions {res.caption}; {res.comments} comments; "
              f"media {res.media or ('not saved: ' + res.media_error if res.media_error else 'not asked for')}")
        if report["balance"]:
            print(f"balance: {report['balance']}")
    else:
        print(f"video-bundle failed: {res.error}", file=sys.stderr)
    return 0 if res.ok and not (args.media and not res.media) else 1
