"""CLI glue for ``gather reddit``: read a subreddit listing or a post with its comments through
Reddit's official Data API, with your own app's credentials from the environment."""

from __future__ import annotations

import sys
from collections.abc import Callable


def add_reddit_parser(sub, add_common: Callable) -> None:
    from gather.reddit import TIMES

    p = sub.add_parser("reddit", help="read Reddit through the official Data API with your own app credentials")
    p.add_argument("target", help="r/NAME, r/NAME/SORT (hot, new, top, rising, controversial), a post URL, "
                                  "or comments/ID")
    p.add_argument("--limit", type=int, default=25, help="posts per listing, 1 to 100")
    p.add_argument("--time", default="day", choices=TIMES, help="time window for top and controversial")
    p.add_argument("--depth", type=int, default=3, help="comment reply depth, 1 to 10")
    p.add_argument("--comment-limit", type=int, default=100, help="comments per thread, 1 to 500")
    add_common(p)
    p.set_defaults(func=cmd_reddit)


def cmd_reddit(args) -> int:
    from gather.commands import _fetch_and_emit
    from gather.reddit import RedditSource

    try:
        src = RedditSource(limit=args.limit, time_window=args.time, depth=args.depth,
                           comment_limit=args.comment_limit)
    except ValueError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 2
    return _fetch_and_emit(lambda: src.fetch(args.target), args)
