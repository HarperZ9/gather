from __future__ import annotations

import html
import json
import re

from gather.item import Item, make_item

_VTT_TAG = re.compile(r"<[^>]+>")


def transcript_from_vtt(vtt: str, *, auto: bool = False) -> str:
    """Plain text from a yt-dlp-style WebVTT caption file.

    Drops the header, NOTE blocks, cue-timing lines, and inline tags (including the inline
    timestamp tags auto-captions carry), decodes HTML entities, and always drops exact
    consecutive duplicate lines (auto-captions re-show the previous line on every cue).

    ``auto`` controls the one lossy step. Auto-captions also grow a line across cues, each
    cue re-emitting the previous line and extending it; when ``auto`` is set, such a line
    replaces its predecessor instead of laddering. It defaults False so manual subtitles
    pass through untouched: a manual cue that legitimately begins with the previous line is
    preserved, not merged. The prefix-growth collapse is deliberately conservative: it does
    not stitch a head-dropping sliding window (where the start of the line scrolls off),
    which is rare in yt-dlp output and would still ladder. Pure and deterministic.
    """
    out: list[str] = []
    in_note = False
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line:
            in_note = False  # a blank line ends a NOTE block
            continue
        if in_note:
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if line.startswith("NOTE"):
            in_note = True
            continue
        if "-->" in line:
            continue
        line = html.unescape(_VTT_TAG.sub("", line)).strip()
        if not line:
            continue
        if auto and out and line.startswith(out[-1]):
            out[-1] = line  # auto-caption still rolling the same line in: replace, do not ladder
        elif not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def parse_video(
    info_json: str,
    vtt: str | None,
    *,
    fetched_at: float,
    method: str = "yt-dlp",
    transcript_method: str | None = None,
    auto_captions: bool = False,
    caption_lang: str | None = None,
) -> list[Item]:
    """Turn a yt-dlp info.json (and optional .vtt captions) into Items. Pure: no network.

    Produces a metadata Item, a transcript Item when captions are present, and a comment
    Item per comment yt-dlp captured. ``method`` stamps the metadata and comments. Set
    ``auto_captions`` when the captions are machine-generated: it both collapses their
    rolling-window growth and, unless ``transcript_method`` overrides it, stamps the
    transcript ``auto-caption`` so it is never recorded as a manual transcript.
    ``caption_lang`` (the yt-dlp track key, such as ``en-orig``) is kept in the transcript's
    meta when given. Each item gets a provenance receipt. Raises ValueError on malformed
    yt-dlp JSON.
    """
    try:
        info = json.loads(info_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid yt-dlp JSON: {exc}") from exc
    if not isinstance(info, dict):
        raise ValueError("not valid yt-dlp JSON: the top level is not an object")
    return items_from_info(info, vtt, fetched_at=fetched_at, method=method,
                           transcript_method=transcript_method, auto_captions=auto_captions,
                           caption_lang=caption_lang)


def items_from_info(
    info: dict,
    vtt: str | None,
    *,
    fetched_at: float,
    method: str = "yt-dlp",
    transcript_method: str | None = None,
    auto_captions: bool = False,
    caption_lang: str | None = None,
) -> list[Item]:
    """``parse_video`` for an already-decoded info dict (the live edge parses its JSON once)."""
    vid = str(info.get("id", ""))
    title = str(info.get("title", ""))
    uploader = str(info.get("uploader") or info.get("channel") or "")
    meta_text = json.dumps(
        {
            "uploader": uploader,
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "view_count": info.get("view_count"),
            "webpage_url": info.get("webpage_url"),
        },
        sort_keys=True,
    )
    items = [
        make_item(
            kind="metadata", id=vid, title=title, text=meta_text,
            source="video", ref=vid, method=method, fetched_at=fetched_at, meta={"uploader": uploader},
        )
    ]
    if vtt:
        tmethod = transcript_method or ("auto-caption" if auto_captions else method)
        tmeta = {"uploader": uploader}
        if caption_lang:
            tmeta["caption_lang"] = caption_lang
        items.append(
            make_item(
                kind="transcript", id=vid, title=title,
                text=transcript_from_vtt(vtt, auto=auto_captions),
                source="video", ref=vid, method=tmethod, fetched_at=fetched_at,
                meta=tmeta,
            )
        )
    items.extend(_comment_items(info, vid, title, method, fetched_at))
    return items


def _comment_items(info: dict, vid: str, title: str, method: str, fetched_at: float) -> list[Item]:
    return [
        make_item(
            kind="comment", id=str(c.get("id", "")), title=f"comment on {title}", text=str(c.get("text", "")),
            source="video", ref=vid, method=method, fetched_at=fetched_at, meta=_comment_meta(c),
        )
        for c in info.get("comments") or []
        if str(c.get("text", ""))
    ]


# Engagement fields carried from a yt-dlp comment into the Item meta: the community's own signal
# (likes, thread position, pin, verified/uploader) so a downstream reader can rank what mattered.
# A field absent from yt-dlp's record stays absent from meta -- an honest null, never a faked 0/False.
_COMMENT_ENGAGEMENT = ("like_count", "parent", "is_pinned", "author_is_verified", "author_is_uploader")


def _comment_meta(c: dict) -> dict:
    meta: dict = {"author": str(c.get("author", ""))}
    for key in _COMMENT_ENGAGEMENT:
        if c.get(key) is not None:
            meta[key] = c[key]
    return meta


# The live edge lives in gather.video_source; re-exported here so existing imports keep working.
from gather.video_source import VideoOutcome, VideoSource  # noqa: E402,F401
