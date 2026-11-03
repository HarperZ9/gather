"""Balanced comment synthesis: what a comment section adds, with critique and support side by side.

``balance(comments)`` reads a video's comments (yt-dlp's records, or a bundle's thread file) and
returns a ``gather.comment-balance/1`` record:

- every comment in exactly one category (``gather.comment_signals``), with its evidence, so
  nothing is dropped without a reason a reader can check;
- substantive comments clustered into claims by shared vocabulary, ranked by comments and likes,
  each with its critique, support and neutral counts and the comment ids behind it;
- groups of likely coordinated promotion (two or more promotional comments that share signals or
  wording) and near-duplicate text from several comments;
- the balance: counts per category and stance, the critique-to-support ratio, and the share of
  likes that went to promotion.

A reply keeps its parent and thread ids. A reply that agrees with its parent takes the parent's
stance toward the video, so agreement with a critique counts as critique.

The record names no commenter: author fields are never read, @mentions are removed from excerpts,
and each excerpt is under 15 words. It is deterministic and uses no model, so the item it becomes
is ``compiled`` (``gather.derive``), never ``synthesized``. Pure.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from gather.comment_signals import AGREE_OPEN, INSULT, MENTION, URL, classify, tokens

FORMAT = "gather.comment-balance/1"
EXCERPT_WORDS = 14
CLAIM_SIM = 0.2
NEAR_DUP = 0.6


def _likes(c: dict) -> int:
    v = c.get("like_count", c.get("score"))
    return v if isinstance(v, int) and v >= 0 else 0


def excerpt(text: str, limit: int = EXCERPT_WORDS) -> str:
    """The first sentence's opening words, at most ``limit``, with links and @mentions removed."""
    plain = re.sub(r"\s+", " ", MENTION.sub("", URL.sub("", text or ""))).strip()
    first = re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0]
    words = first.split()
    return " ".join(words[:limit]) + (" ..." if len(words) > limit else "")


def flatten(tree: list[dict]) -> list[dict]:
    """A thread file's nested comments as a flat list, each reply with its parent id."""
    out: list[dict] = []
    stack = [(c, None) for c in reversed(tree)]
    while stack:
        c, parent = stack.pop()
        out.append({**{k: v for k, v in c.items() if k != "replies"}, "parent": c.get("parent") or parent})
        stack.extend((r, c.get("id")) for r in reversed(c.get("replies") or []))
    return out


def _records(comments: list[dict]) -> list[dict]:
    ids = {str(c.get("id")) for c in comments}
    recs: list[dict[str, Any]] = []
    for c in comments:
        parent = c.get("parent")
        parent = None if parent in (None, "", "root") else str(parent)
        s = classify(str(c.get("text") or ""), from_channel=bool(c.get("author_is_uploader")))
        recs.append({"id": str(c.get("id")), "parent": parent, "parent_missing": bool(parent and parent not in ids),
                     "category": s.category, "stance": s.stance, "evidence": s.evidence, "promo": s.promo,
                     "likes": _likes(c), "words": s.words, "question": s.question, "pointer": s.pointer,
                     "_text": str(c.get("text") or ""), "_tokens": tokens(str(c.get("text") or ""))})
    by = {r["id"]: r for r in recs}
    for r in recs:
        root, seen = r, set()
        while root["parent"] and root["parent"] in by and root["id"] not in seen:
            seen.add(root["id"])
            root = by[root["parent"]]
        r["thread"] = root["id"]
        p = by.get(r["parent"] or "")
        opens = r["stance"] == "support" or bool(AGREE_OPEN.match(r["_text"]))
        agrees = p is not None and opens and p["category"] == "substantive" and p["stance"] in ("critique", "support")
        r["toward_video"] = p["stance"] if agrees and p else r["stance"]
        r["agrees_with_parent"] = agrees
    return recs


def _shingles(toks: list[str]) -> set[tuple[str, ...]]:
    return {tuple(toks[i:i + 3]) for i in range(max(0, len(toks) - 2))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _groups(recs: list[dict], linked) -> list[list[dict]]:
    parent = list(range(len(recs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            if linked(recs[i], recs[j]):
                parent[find(i)] = find(j)
    out: dict[int, list[dict]] = {}
    for i, r in enumerate(recs):
        out.setdefault(find(i), []).append(r)
    return [g for g in out.values() if len(g) > 1]


def mark_coordination(recs: list[dict]) -> list[dict]:
    """Groups of likely coordinated comments, marked ``coordinated_spam`` in place: promotional
    comments that share two signals or a third of their wording, and three or more comments of
    eight words or more with near-identical text."""
    promo = [r for r in recs if r["category"] == "promotional"]
    groups: list[dict[str, Any]] = [{"kind": "promotion with shared signals", "members": g} for g in _groups(
        promo, lambda a, b: len(set(a["promo"]) & set(b["promo"])) >= 2
        or _jaccard(_shingles(a["_tokens"]), _shingles(b["_tokens"])) >= 0.33)]
    long = [r for r in recs if r["words"] >= 8 and r["category"] not in ("channel", "promotional")]
    for dup in _groups(long, lambda a, b: _jaccard(_shingles(a["_tokens"]), _shingles(b["_tokens"])) >= NEAR_DUP):
        if len(dup) >= 3:
            groups.append({"kind": "near-identical text", "members": dup})
    out = []
    for n, g in enumerate(groups, 1):
        shared = sorted(set.intersection(*(set(m["promo"]) for m in g["members"]))) if g["kind"].startswith("promotion") else []
        for m in g["members"]:
            m["category"], m["group"] = "coordinated_spam", n
        out.append({"group": n, "kind": g["kind"], "comments": [m["id"] for m in g["members"]], "shared_signals": shared,
                    "likes": sum(m["likes"] for m in g["members"])})
    return out


def _vectors(recs: list[dict]) -> list[dict[str, float]]:
    """tf-idf vectors of unit length. A word in more than a third of the comments (the video's own
    topic word) and a word only one comment uses carry no grouping weight."""
    df = Counter(t for r in recs for t in set(r["_tokens"]))
    n = len(recs)
    vecs = []
    for r in recs:
        tf = Counter(t for t in r["_tokens"] if 1 < df[t] <= max(2, n / 3))
        v = {t: (1 + math.log(c)) * math.log(1 + n / df[t]) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def cluster_claims(recs: list[dict]) -> list[dict]:
    """Substantive comments grouped into claims. Most-liked first, each comment joins the closest
    claim at or above ``CLAIM_SIM``; a reply below that joins its parent's claim, so a conversation
    stays together. Claims are ranked by comments, then likes."""
    sub = sorted((r for r in recs if r["category"] == "substantive"), key=lambda r: (-r["likes"], r["id"]))
    vecs = dict(zip((r["id"] for r in sub), _vectors(sub)))
    claims: list[dict] = []
    home: dict[str, dict] = {}
    for r in sub:
        v = vecs[r["id"]]
        best, score = None, 0.0
        for c in claims:
            s = _cos(v, c["centroid"]) / (math.sqrt(sum(x * x for x in c["centroid"].values())) or 1.0)
            if s > score:
                best, score = c, s
        if score < CLAIM_SIM:
            best = home.get(r["parent"] or "") or None
        if best is None:
            best = {"centroid": {}, "members": []}
            claims.append(best)
        best["members"].append(r)
        for t, x in v.items():
            best["centroid"][t] = best["centroid"].get(t, 0.0) + x
        home[r["id"]] = best
    return [_claim(c) for c in sorted(claims, key=lambda c: (-len(c["members"]), -sum(m["likes"] for m in c["members"])))]


def _claim(c: dict) -> dict:
    members = c["members"]
    # the excerpt comes from the most-liked member that attacks no one, when there is one
    civil = [m for m in members if not INSULT.search(m["_text"])] or members
    top = max(civil, key=lambda m: (m["likes"], m["words"]))
    stances = Counter(m["toward_video"] for m in members)
    terms = [t for t, _ in sorted(c["centroid"].items(), key=lambda kv: -kv[1])[:4]]
    return {"terms": terms, "comments": [m["id"] for m in members], "top_level": sum(1 for m in members if not m["parent"]),
            "replies": sum(1 for m in members if m["parent"]), "critique": stances["critique"], "support": stances["support"],
            "mixed": stances["mixed"], "neutral": stances["neutral"], "likes": sum(m["likes"] for m in members),
            "excerpt": {"comment": top["id"], "text": excerpt(top["_text"])}, "threads": sorted({m["thread"] for m in members})}


CATEGORIES = ("substantive", "reaction", "ad_hominem", "dismissal", "promotional", "coordinated_spam", "channel")


def _balance_line(crit: int, supp: int) -> str:
    if not crit and not supp:
        return "No substantive comment takes a side, so there is no balance to report."
    ratio = min(crit, supp) / max(crit, supp)
    if ratio >= 0.5:
        return f"Critique and support are both well represented: {crit} and {supp} substantive comments."
    side, other = ("critique", "support") if crit > supp else ("support", "critique")
    return f"Weighted toward {side}: {max(crit, supp)} {side} against {min(crit, supp)} {other} among substantive comments."


def balance(comments: list[dict], *, title: str = "", url: str = "", max_claims: int = 20) -> dict:
    """The balanced synthesis of one video's comments. ``comments`` are flat records with ``id``,
    ``parent`` (None, ``"root"`` or a comment id), ``text``, ``like_count`` and optionally
    ``author_is_uploader``; any author field is ignored. Pure and deterministic."""
    recs = _records(comments)
    groups = mark_coordination(recs)
    claims = cluster_claims(recs)
    cats = Counter(r["category"] for r in recs)
    sub = [r for r in recs if r["category"] == "substantive"]
    toward = Counter(r["toward_video"] for r in sub)
    likes = sum(r["likes"] for r in recs)
    spam_likes = sum(r["likes"] for r in recs if r["category"] in ("promotional", "coordinated_spam"))
    top10 = sorted(recs, key=lambda r: -r["likes"])[:10]
    public = [{k: v for k, v in r.items() if not k.startswith("_") and k != "promo"} for r in recs]
    return {
        "format": FORMAT, "title": title, "url": url, "method": "compiled",
        "counts": {"comments": len(recs), "top_level": sum(1 for r in recs if not r["parent"]), "replies": sum(1 for r in recs if r["parent"]),
                   "replies_parent_missing": sum(1 for r in recs if r["parent_missing"]), **{c: cats[c] for c in CATEGORIES}},
        "balance": {"critique": toward["critique"], "support": toward["support"], "mixed": toward["mixed"], "neutral": toward["neutral"],
                    "questions": sum(1 for r in sub if r["question"]), "pointers": sum(1 for r in sub if r["pointer"]),
                    "sentence": _balance_line(toward["critique"], toward["support"]),
                    "likes_total": likes, "likes_to_promotion": spam_likes,
                    "top10_by_likes": dict(Counter(r["category"] if r["category"] != "substantive" else f"substantive:{r['toward_video']}" for r in top10))},
        "claims": claims[:max_claims], "claims_total": len(claims), "coordinated": groups, "comments": public,
    }
