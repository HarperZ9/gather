"""Reddit API records to Items. Pure: no network.

Field names in ``meta`` follow the Telos reach reader's normalised post and comment shapes
(id, subreddit, author, score, comments, created_utc, url, permalink; depth for comments), so
the two tools describe a Reddit read the same way. The receipt fingerprints the full text: a post
is its title, a blank line and its body (or link); a comment is its body.
"""

from __future__ import annotations

from gather.item import Item, make_item

REDDIT = "https://www.reddit.com"


def _permalink(d: dict) -> str:
    link = d.get("permalink")
    return f"{REDDIT}{link}" if isinstance(link, str) and link.startswith("/") else ""


def post_item(child: dict, method: str, fetched_at: float) -> Item:
    d = child.get("data") or {}
    title = str(d.get("title") or "")
    body = d.get("selftext") if isinstance(d.get("selftext"), str) and d.get("selftext") else ""
    link = str(d.get("url") or "")
    text = f"{title}\n\n{body or link}".rstrip()
    ref = _permalink(d) or f"{REDDIT}/comments/{d.get('id', '')}"
    meta = {"id": d.get("id"), "subreddit": d.get("subreddit"), "author": d.get("author"),
            "score": d.get("score"), "comments": d.get("num_comments"),
            "created_utc": d.get("created_utc"), "url": link or None, "permalink": _permalink(d) or None}
    return make_item(kind="post", id=f"t3_{d.get('id', '')}", title=title, text=text, source="reddit",
                     ref=ref, method=method, fetched_at=fetched_at,
                     meta={k: v for k, v in meta.items() if v is not None})


def flatten(children: list, depth: int = 0) -> list[tuple[dict, int]]:
    """A comment tree as a depth-first list of ``(data, depth)``. "More comments" stubs are
    skipped: reading them takes further requests this source does not make."""
    out: list[tuple[dict, int]] = []
    for child in children or []:
        if not isinstance(child, dict) or child.get("kind") != "t1":
            continue
        d = child.get("data") or {}
        out.append((d, depth))
        replies = d.get("replies")
        if isinstance(replies, dict):
            out.extend(flatten((replies.get("data") or {}).get("children") or [], depth + 1))
    return out


def comment_items(children: list, post: Item, method: str, fetched_at: float) -> list[Item]:
    items = []
    for d, depth in flatten(children):
        body = str(d.get("body") or "")
        if not body:
            continue
        meta = {"id": d.get("id"), "author": d.get("author"), "score": d.get("score"), "depth": depth,
                "created_utc": d.get("created_utc"), "parent_id": d.get("parent_id"),
                "permalink": _permalink(d) or None}
        items.append(make_item(kind="comment", id=f"t1_{d.get('id', '')}", title=f"comment on {post.title}",
                               text=body, source="reddit", ref=_permalink(d) or post.provenance.ref,
                               method=method, fetched_at=fetched_at,
                               meta={k: v for k, v in meta.items() if v is not None}))
    return items
