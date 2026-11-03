"""The balanced comment synthesis as a page a person reads, and as a receipted Gather item.

``report_markdown`` renders a ``gather.comment-balance/1`` record: the balance first, then the
substantive claims ranked with their counts and one short excerpt each, then what was set aside and
why, every group with the comment ids behind it. It names no commenter. ``balance_item`` wraps the
page as a ``compiled`` derived item over the comment items it read (``gather.derive``), so the
receipt says it was assembled by rules and points back to the exact comments.
"""

from __future__ import annotations

from gather.derive import COMPILED, derive
from gather.item import Item

SET_ASIDE = (
    ("coordinated_spam", "Likely coordinated spam"),
    ("promotional", "Promotion from a single comment"),
    ("ad_hominem", "About the person, not the argument"),
    ("dismissal", "Dismissal with no reason given"),
    ("reaction", "Short reactions"),
    ("channel", "From the channel itself"),
)


def _ids(ids: list[str], limit: int = 12) -> str:
    shown = ", ".join(ids[:limit])
    return shown + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def _claim_lines(n: int, c: dict) -> list[str]:
    sides = ", ".join(f"{c[k]} {k}" for k in ("critique", "support", "mixed", "neutral") if c[k])
    return [f"{n}. **{', '.join(c['terms']) or 'untitled'}**: {len(c['comments'])} comments ({c['top_level']} top-level, "
            f"{c['replies']} replies; {sides}), {c['likes']} likes.",
            f"   Excerpt: \"{c['excerpt']['text']}\" (comment {c['excerpt']['comment']})",
            f"   Comments: {_ids(c['comments'])}", ""]


def report_markdown(rec: dict) -> str:
    """The record as Markdown: balance, ranked claims, what was set aside, and how it was made."""
    k, b = rec["counts"], rec["balance"]
    out = [f"# Comment balance{': ' + rec['title'] if rec.get('title') else ''}", ""]
    if rec.get("url"):
        out += [f"Source: {rec['url']}", ""]
    missing = k["replies_parent_missing"]
    orphans = f", {missing} of them with a parent that was not loaded" if missing else ""
    out += [f"{k['comments']} comments read: {k['top_level']} top-level and {k['replies']} replies{orphans}.",
            "Commenters are not named. Each excerpt is under 15 words.", "", "## Balance", "", f"- {b['sentence']}",
            f"- Substantive comments: {k['substantive']} ({b['critique']} critique, {b['support']} support, {b['mixed']} mixed, "
            f"{b['neutral']} neutral; {b['questions']} ask a question, {b['pointers']} point to a source).",
            f"- Set aside: {k['coordinated_spam']} likely coordinated spam, {k['promotional']} other promotion, {k['ad_hominem']} about the "
            f"person, {k['dismissal']} dismissals, {k['reaction']} short reactions, {k['channel']} from the channel.",
            f"- Likes: {b['likes_total']} in all, {b['likes_to_promotion']} of them on promotion.",
            f"- The 10 most-liked comments: {', '.join(f'{v} {n}' for n, v in sorted(b['top10_by_likes'].items(), key=lambda kv: -kv[1]))}.", "",
            "## Substantive claims, ranked", ""]
    for n, c in enumerate(rec["claims"], 1):
        out += _claim_lines(n, c)
    if rec["claims_total"] > len(rec["claims"]):
        out += [f"{rec['claims_total'] - len(rec['claims'])} smaller claims are in the JSON record.", ""]
    out += ["## Set aside, with the reason", ""]
    for g in rec["coordinated"]:
        why = f"shared signals: {', '.join(g['shared_signals'])}" if g["shared_signals"] else g["kind"]
        out.append(f"- Group {g['group']}, {g['kind']}: {len(g['comments'])} comments, {g['likes']} likes ({why}). Comments: {_ids(g['comments'])}")
    for cat, label in SET_ASIDE[1:]:
        ids = [r["id"] for r in rec["comments"] if r["category"] == cat]
        if ids:
            out.append(f"- {label}: {len(ids)}. Comments: {_ids(ids, 8)}")
    out += ["", "## How this was made", "",
            "Deterministic rules, no model: the method is `compiled`. Categories come from word patterns, and an argument "
            "marker outweighs an insult, so a harsh critique that gives a reason stays substantive. Claims group comments by "
            "shared vocabulary. Sarcasm and irony can be misread. A reply that agrees with its parent counts toward the "
            "parent's side.", ""]
    return "\n".join(out)


def balance_item(rec: dict, inputs: list[Item], *, fetched_at: float, ref: str) -> Item:
    """The page as a ``compiled`` item derived from the comment items it read."""
    return derive(inputs, report_markdown(rec), fetched_at=fetched_at, ref=ref, method=COMPILED,
                  title=f"comment balance: {rec.get('title') or ref}", kind="synthesis", source="synthesis")
