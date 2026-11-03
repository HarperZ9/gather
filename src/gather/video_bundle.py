"""A video as one bundle folder: captions, transcript, chapters, metadata, comments, optional media.

``write_bundle`` is pure of the network: from yt-dlp's info (with ``comments``), one caption track
and an optional media file already in the folder, it writes

- ``<id>.video.json`` (``gather.video/1``): what the video is, its chapters, where the captions
  came from, and the media file's name; no format lists or signed stream addresses, which carry
  the viewer's IP address;
- ``<id>.<lang>.vtt``, ``<id>.transcript.txt`` (``[HH:MM:SS] words``) and
  ``<id>.transcript.plain.txt`` (paragraphs);
- ``<id>.thread.json`` (``gather.video-thread/1``): the comment tree, each reply under its parent,
  with like counts; and ``<id>.comments.txt``, the same tree to read, without names;
- with ``balance``, ``<id>.balance.json`` and ``<id>.balance.md`` (``gather.comment_balance``);
- ``SOURCE.txt`` and ``SHA256SUMS`` (``sha256sum`` lines over every other file).

The layout matches the bundle CMMNS writes (``cmmns media fetch --full``). The media file is a
local research copy: Gather never uploads, shares or publishes it.
"""

from __future__ import annotations

import hashlib
import html
import os
import re

FORMAT = "gather.video/1"
THREAD_FORMAT = "gather.video-thread/1"
MEDIA_NOTE = "The media file is a local research copy kept on this computer. Gather does not upload, share or publish it."
_TIME = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?")
_TAG = re.compile(r"<[^>]+>")


def clock(sec: float) -> str:
    s = max(0, int(sec or 0))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _seconds(t: str) -> float | None:
    m = _TIME.match(t or "")
    if not m:
        return None
    return int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3]) + (int(m[4].ljust(3, "0")) / 1000 if m[4] else 0)


def vtt_segments(vtt: str) -> list[dict]:
    """WebVTT cues as ``{start, end, text}``. Machine captions repeat the line before and grow a
    line across cues: a line already said is dropped, and one that only extends the line before
    replaces it, so each spoken line is kept once."""
    out: list[dict] = []
    said: list[str] = []
    for block in re.split(r"\n{2,}", (vtt or "").replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if at is None:
            continue
        a, _, b = lines[at].partition("-->")
        start, end = _seconds(a), _seconds(b.strip())
        if start is None:
            continue
        for raw in lines[at + 1:]:
            text = re.sub(r"\s+", " ", html.unescape(_TAG.sub("", raw))).strip()
            if not text or text in said:
                continue
            if out and text.startswith(out[-1]["text"]):
                out[-1]["text"], said[-1] = text, text
                out[-1]["end"] = end if end is not None else out[-1]["end"]
                continue
            out.append({"start": start, "end": end if end is not None else start, "text": text})
            said = (said + [text])[-4:]
    return out


def timed_transcript(segs: list[dict]) -> str:
    return "".join(f"[{clock(s['start'])}] {s['text']}\n" for s in segs)


def plain_transcript(segs: list[dict]) -> str:
    """The words as paragraphs: a new one after a pause of 3 s or more, or about 120 words."""
    paras: list[str] = []
    cur: list[str] = []
    count, prev = 0, None
    for s in segs:
        if cur and ((prev is not None and s["start"] - prev >= 3) or count >= 120):
            paras.append(" ".join(cur))
            cur, count = [], 0
        cur.append(s["text"])
        count += len(s["text"].split())
        prev = s["end"] if s["end"] is not None else s["start"]
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras) + "\n" if paras else ""


_COMMENT_KEYS = ("id", "parent", "text", "like_count", "timestamp", "_time_text", "is_pinned", "author_is_uploader", "author", "is_favorited")


def comment_tree(comments: list[dict]) -> list[dict]:
    """yt-dlp's flat comments as a tree. A reply goes under its parent when the parent was read;
    otherwise it stays at the top with ``parent_missing`` set, never passed off as a top comment."""
    nodes: dict[str, dict] = {}
    order: list[str] = []
    for c in comments or []:
        cid = str(c.get("id") or f"anon-{len(order)}")
        if cid not in nodes:
            order.append(cid)
        node = {k: c[k] for k in _COMMENT_KEYS if c.get(k) is not None}
        node["id"], node["replies"] = cid, []
        node["parent"] = None if c.get("parent") in (None, "", "root") else str(c["parent"])
        nodes[cid] = node
    roots = []
    for cid in order:
        n = nodes[cid]
        p = nodes.get(n["parent"] or "")
        if p is not None and p is not n:
            p["replies"].append(n)
        else:
            if n["parent"]:
                n["parent_missing"] = True
            roots.append(n)
    return roots


def comments_text(tree: list[dict]) -> str:
    """The tree to read: ``[likes] text``, replies indented under their parent. No names."""
    out: list[str] = []

    def put(n: dict, depth: int) -> None:
        pad = "   " * depth + ("> " if depth else "")
        text = re.sub(r"\s*\n\s*", " ", str(n.get("text") or "")).strip()
        out.append(f"{pad}[{n.get('like_count', 0) or 0}] {text}")
        for r in n["replies"]:
            put(r, depth + 1)

    for n in tree:
        put(n, 0)
    return "\n".join(out) + ("\n" if out else "")


def video_record(info: dict, *, caption: dict | None, segments: int, media: list[str] | None, fetched_at: float) -> dict:
    keys = ("id", "title", "channel", "channel_url", "uploader", "uploader_id", "upload_date", "duration", "view_count",
            "like_count", "comment_count", "description", "tags", "categories", "webpage_url", "live_status")
    rec = {"format": FORMAT, **{k: info.get(k) for k in keys}}
    rec["chapters"] = [{"start": c.get("start_time", 0), "at": clock(c.get("start_time", 0)), "title": c.get("title", "")}
                       for c in info.get("chapters") or []]
    rec["captions"] = {**caption, "segments": segments} if caption else None
    rec["media"] = {"file": media[0], "files": list(media), "note": MEDIA_NOTE} if media else None
    rec["fetched_at"] = fetched_at
    return rec


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_source_and_sums(out_dir: str, *, url: str, title: str, how: str, media: str | None, when: str) -> list[str]:
    """SOURCE.txt, then SHA256SUMS over every file in the folder. Returns the files listed."""
    files = sorted(f for f in os.listdir(out_dir) if f not in ("SOURCE.txt", "SHA256SUMS") and os.path.isfile(os.path.join(out_dir, f)))
    lines = [f"Source: {url}" + (f" ({title})" if title else ""), f"Fetched: {when}", f"How: {how}",
             f"Media file: {media + '. ' + MEDIA_NOTE if media else 'not saved'}", "Files:", *(f"- {f}" for f in files)]
    with open(os.path.join(out_dir, "SOURCE.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    listed = [*files, "SOURCE.txt"]
    with open(os.path.join(out_dir, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{sha256_file(os.path.join(out_dir, n))} *{n}\n" for n in listed))
    return listed
