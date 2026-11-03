"""Writing a video bundle (``gather.video_bundle``) and fetching one through yt-dlp.

``write_bundle`` turns yt-dlp's info, one caption track and an optional media file already in the
folder into every bundle file, and runs the balanced comment synthesis when asked. Pure of the
network, so it is tested on a folder the test makes.

``fetch_bundle`` is the live edge. It runs the same ``VideoSource`` calls as ``gather video`` (one
extraction with comments, one caption download from the saved info), and, only when the caller
asks for the media file, one more yt-dlp call that downloads it from the saved info. Every call
goes through ``gather.spawn`` with ``--ignore-config``; a bot check stops the bundle.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field

from gather.comment_balance import balance
from gather.comment_report import report_markdown
from gather.spawn import find_tool
from gather.video_bundle import (
    THREAD_FORMAT,
    comment_tree,
    comments_text,
    plain_transcript,
    timed_transcript,
    video_record,
    vtt_segments,
    write_source_and_sums,
)
from gather.video_source import VideoOutcome, VideoSource
from gather.ytdlp import failure_text, without_impersonation

MEDIA_TIMEOUT = 3600.0
MEDIA_EXT = ("mp4", "webm", "mkv", "m4a", "mp3", "opus")
DEFAULT_MAX_COMMENTS = 600


@dataclass(slots=True)
class BundleResult:
    out_dir: str
    video_id: str = ""
    files: list[str] = field(default_factory=list)
    caption: str = "skipped"
    comments: int = 0
    media: str | None = None
    media_error: str | None = None
    error: str | None = None
    outcome: VideoOutcome | None = None
    balance: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _put(out_dir: str, name: str, text: str) -> str:
    with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return name


def write_bundle(out_dir: str, info: dict, *, vtt: str | None = None, caption: dict | None = None,
                 media: list[str] | None = None, with_balance: bool = True, fetched_at: float | None = None,
                 how: str = "yt-dlp through gather video-bundle") -> BundleResult:
    """Every bundle file from ``info`` (yt-dlp's, with ``comments``) and the caption text."""
    os.makedirs(out_dir, exist_ok=True)
    when = time.time() if fetched_at is None else fetched_at
    vid = str(info.get("id") or "video")
    res = BundleResult(out_dir=out_dir, video_id=vid, media=", ".join(media) if media else None, caption=(caption or {}).get("kind") or "missing")
    segs = vtt_segments(vtt) if vtt else []
    if vtt and caption:
        _put(out_dir, f"{vid}.{caption.get('lang') or 'und'}.vtt", vtt)
    if segs:
        _put(out_dir, f"{vid}.transcript.txt", timed_transcript(segs))
        _put(out_dir, f"{vid}.transcript.plain.txt", plain_transcript(segs))
    comments = info.get("comments") or []
    tree = comment_tree(comments)
    thread = {"format": THREAD_FORMAT, "video": vid, "url": info.get("webpage_url"), "comment_count_reported": info.get("comment_count"),
              "captured": len(comments), "top_level": len(tree), "comments": tree}
    _put(out_dir, f"{vid}.thread.json", json.dumps(thread, indent=2, ensure_ascii=False) + "\n")
    _put(out_dir, f"{vid}.comments.txt", comments_text(tree))
    rec = video_record(info, caption=caption, segments=len(segs), media=media, fetched_at=when)
    _put(out_dir, f"{vid}.video.json", json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    if with_balance and comments:
        res.balance = balance(comments, title=str(info.get("title") or ""), url=str(info.get("webpage_url") or ""))
        _put(out_dir, f"{vid}.balance.json", json.dumps(res.balance, indent=2, ensure_ascii=False) + "\n")
        _put(out_dir, f"{vid}.balance.md", report_markdown(res.balance))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))
    cap = f"{caption.get('kind')} captions ({caption.get('lang')})" if caption and segs else "no captions"
    res.files = write_source_and_sums(out_dir, url=str(info.get("webpage_url") or ""), title=str(info.get("title") or ""),
                                      how=f"{how}: {cap}, {len(comments)} comments with replies", media=res.media, when=stamp)
    res.comments = len(comments)
    return res


def download_media(source: VideoSource, info: dict, out_dir: str, out: VideoOutcome,
                   timeout: float = MEDIA_TIMEOUT) -> tuple[list[str], str | None]:
    """The media into ``out_dir``, from the saved info (no second extraction). Returns (file
    names, None) or ([], the failure line). With ffmpeg on PATH the best video and audio are
    merged into one MP4. Without it, a file that holds both is taken when the site offers one,
    and otherwise the best video and the best audio are saved as two files, never re-encoded."""
    vid = str(info.get("id") or "video")
    slim = without_impersonation({k: v for k, v in info.items() if k != "comments"})
    merge = bool(find_tool("ffmpeg"))
    fmt, name = ("bv*+ba/b", "%(id)s.%(ext)s") if merge else ("b/bv*,ba", "%(id)s.%(format_id)s.%(ext)s")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "info.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(slim, f)
        argv = source.base_argv + ["--load-info-json", path, "-f", fmt, *(["--merge-output-format", "mp4"] if merge else []),
                                   "--no-overwrites", "-o", os.path.join(os.path.abspath(out_dir), name)]
        res = source._call(argv, "media", out, timeout=timeout)
    if not res.ok:
        return [], failure_text(res)
    found = sorted(f for f in os.listdir(out_dir) if f.startswith(vid + ".") and f.rsplit(".", 1)[-1] in MEDIA_EXT)
    return (found, None) if found else ([], "yt-dlp wrote no media file")


def fetch_bundle(url: str, out_dir: str, source: VideoSource, *, media: bool = False, with_balance: bool = True,
                 clock=time.time) -> BundleResult:
    """One video, live: metadata and comments, the chosen caption track, the media file when asked."""
    out = VideoOutcome(target=url)
    info = source._extract(url, out)
    if info is None:
        return BundleResult(out_dir=out_dir, error=out.error, outcome=out)
    vtt = source._captions_for(info, out) if source.captions != "skip" else None
    caption = {"lang": out.caption_lang, "kind": out.caption, "from": "yt-dlp WebVTT"} if vtt else None
    os.makedirs(out_dir, exist_ok=True)
    names, why = download_media(source, info, out_dir, out) if media and out.bot_check is None else ([], None)
    res = write_bundle(out_dir, info, vtt=vtt, caption=caption, media=names or None, with_balance=with_balance, fetched_at=float(clock()))
    res.media_error, res.outcome = why, out
    if not vtt:
        res.caption = f"missing ({out.caption_reason or 'skipped'})"
    return res
