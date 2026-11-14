"""Writing a video bundle (``gather.video_bundle``) and fetching one through yt-dlp.

``write_bundle`` turns yt-dlp's info, one caption track and an optional media file already in the
folder into every bundle file, and runs the balanced comment synthesis when asked. Pure of the
network, so it is tested on a folder the test makes.

``fetch_bundle`` is the live edge. It runs the same ``VideoSource`` calls as ``gather video`` (one
extraction with comments, one caption download from the saved info), and, only when the caller
asks for the media file, one more yt-dlp call that downloads it from the saved info. Every call
goes through ``gather.spawn`` with ``--ignore-config``; a bot check stops the bundle.

The caption download and the frame stage (``gather.video_frames``) run side by side. With
``fast`` they start as soon as yt-dlp has read the page, while the same yt-dlp call goes on to
read the comments: yt-dlp writes its info to a file at that point (``--print-to-file`` at
``pre_process``), so one extraction still serves everything. ``timings`` on the result holds
the seconds each stage took.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from gather.comment_balance import balance
from gather.comment_report import report_markdown
from gather.frame_sheets import available as frames_available
from gather.pacing import HostLimiter
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
from gather.video_frames import (
    Fetcher,
    FrameFetch,
    fetch_frames,
    frame_record,
    frames_line,
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
    frames: str = "frames: not requested"
    timings: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


def _put(out_dir: str, name: str, text: str) -> str:
    with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return name


def write_bundle(out_dir: str, info: dict, *, vtt: str | None = None, caption: dict | None = None,
                 media: list[str] | None = None, with_balance: bool = True, fetched_at: float | None = None,
                 how: str = "yt-dlp through gather video-bundle", frames: dict | str | None = None) -> BundleResult:
    """Every bundle file from ``info`` (yt-dlp's, with ``comments``) and the caption text.
    ``frames`` is the record of contact sheets already written into ``out_dir``."""
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
    rec = video_record(info, caption=caption, segments=len(segs), media=media, fetched_at=when, frames=frames)
    res.frames = frames_line(frames)
    _put(out_dir, f"{vid}.video.json", json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    if with_balance and comments:
        res.balance = balance(comments, title=str(info.get("title") or ""), url=str(info.get("webpage_url") or ""))
        _put(out_dir, f"{vid}.balance.json", json.dumps(res.balance, indent=2, ensure_ascii=False) + "\n")
        _put(out_dir, f"{vid}.balance.md", report_markdown(res.balance))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))
    cap = f"{caption.get('kind')} captions ({caption.get('lang')})" if caption and segs else "no captions"
    res.files = write_source_and_sums(out_dir, url=str(info.get("webpage_url") or ""), title=str(info.get("title") or ""),
                                      how=f"{how}: {cap}, {len(comments)} comments with replies, {res.frames}", media=res.media, when=stamp)
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


def _early_info(path: str, extraction: Future, poll: float = 0.05) -> dict | None:
    """yt-dlp's info as soon as it is on disk (the page is read, the comments are not yet), or
    None when the call ended before a whole line was written. Keys that start ``__`` hold
    yt-dlp's own working state, not data, and are dropped."""
    while True:
        ended = extraction.done()
        try:
            with open(path, encoding="utf-8") as f:
                line = f.readline()
            info = json.loads(line) if line.endswith("\n") else None
        except (OSError, ValueError):
            info = None  # not there yet, or half written: look again
        if isinstance(info, dict):
            return {k: v for k, v in info.items() if not k.startswith("__")}
        if ended:
            return None
        time.sleep(poll)


@dataclass(slots=True)
class _Side:
    """The caption download and the frame stage, running beside each other."""

    captions: Future
    frames: Future
    outcome: VideoOutcome
    stop: threading.Event


def _start_side(pool: ThreadPoolExecutor, source: VideoSource, info: dict, target: str, timings: dict, *,
                frames: bool, fetcher: Fetcher | None, limiter: HostLimiter | None) -> _Side:
    cap_out, stop = VideoOutcome(target=target), threading.Event()

    def captions() -> str | None:
        began = time.perf_counter()
        vtt = source._captions_for(info, cap_out) if source.captions != "skip" else None
        timings["captions_s"] = round(time.perf_counter() - began, 2)
        return vtt

    def sprites() -> FrameFetch | None:
        began = time.perf_counter()
        got = fetch_frames(info, fetcher=fetcher, limiter=limiter, stop=stop) if frames and frames_available() else None
        timings["frames_fetch_s"] = round(time.perf_counter() - began, 2)
        return got

    return _Side(pool.submit(captions), pool.submit(sprites), cap_out, stop)


def _merge_captions(out: VideoOutcome, cap: VideoOutcome) -> None:
    out.caption, out.caption_lang = cap.caption, cap.caption_lang
    out.caption_reason, out.caption_detail = cap.caption_reason, cap.caption_detail
    out.attempts.extend(cap.attempts)
    out.throttled = out.throttled or cap.throttled
    out.bot_check = out.bot_check or cap.bot_check


def fetch_bundle(url: str, out_dir: str, source: VideoSource, *, media: bool = False, with_balance: bool = True,
                 clock=time.time, fast: bool = False, frames: bool = True, fetcher: Fetcher | None = None,
                 limiter: HostLimiter | None = None) -> BundleResult:
    """One video, live: metadata and comments, the chosen caption track, contact sheets from the
    preview storyboard, the media file when asked. With ``fast`` the captions and the sprite
    images are read while yt-dlp is still reading comments."""
    out, began = VideoOutcome(target=url), time.perf_counter()
    timings: dict = {}

    def side_for(info: dict) -> _Side:
        return _start_side(pool, source, info, url, timings, frames=frames, fetcher=fetcher, limiter=limiter)

    with tempfile.TemporaryDirectory() as d, ThreadPoolExecutor(max_workers=3) as pool:
        early_path = os.path.join(d, "early.json")
        extraction = pool.submit(source._extract, url, out, *([early_path] if fast else []))
        early = _early_info(early_path, extraction) if fast else None
        if early is not None:
            timings["metadata_s"] = round(time.perf_counter() - began, 2)
        side = side_for(early) if early is not None else None
        info = extraction.result()
        timings["extract_s"] = round(time.perf_counter() - began, 2)
        if info is None:
            if side is not None:
                side.stop.set()
            return BundleResult(out_dir=out_dir, error=out.error, outcome=out, timings=timings)
        side = side or side_for(info)
        vtt, got = side.captions.result(), side.frames.result()
    _merge_captions(out, side.outcome)
    caption = {"lang": out.caption_lang, "kind": out.caption, "from": "yt-dlp WebVTT"} if vtt else None
    os.makedirs(out_dir, exist_ok=True)
    names, why = download_media(source, info, out_dir, out) if media and out.bot_check is None else ([], None)
    wrote = time.perf_counter()
    rec = frame_record(out_dir, str(info.get("id") or "video"), got, asked=frames)
    res = write_bundle(out_dir, info, vtt=vtt, caption=caption, media=names or None, with_balance=with_balance,
                       fetched_at=float(clock()), frames=rec)
    timings["write_s"], timings["total_s"] = round(time.perf_counter() - wrote, 2), round(time.perf_counter() - began, 2)
    res.media_error, res.outcome, res.timings = why, out, timings
    if not vtt:
        res.caption = f"missing ({out.caption_reason or 'skipped'})"
    return res
