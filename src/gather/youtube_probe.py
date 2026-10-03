"""A throttle check for the yt-dlp path on a fixed, small set of public videos.

``run_probe`` gathers each probe video once, one at a time, with a pause between them, and
measures the metadata call (seconds per call, calls per minute) and the caption download
(seconds and bytes per second). It never downloads video or audio: Gather does not fetch media
streams. The verdict:

- ``throttled``: a call met a rate limit or a bot check, or the median metadata call took longer
  than ``SLOW_METADATA_S``;
- ``failing``: no probe video could be read, for another reason;
- ``ok``: otherwise.

The probe sends at most two requests per video (one extraction, one caption track) and waits at
least ``MIN_GAP_S`` between videos, so it stays at a single user's pace. Run it before a long
pass, or when a pass slows down, to decide whether to keep going on yt-dlp.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence
from typing import Any

from gather.youtube_route import TimedRunner

PROBE_SCHEMA = "gather.youtube-probe/1"
# Long-standing public videos with caption tracks: YouTube's first upload, an official music
# video and a TED talk. Fixed, so probe runs compare across days.
PROBE_VIDEOS = ("jNQXAC9IVRw", "dQw4w9WgXcQ", "arj7oStGLkU")
MIN_GAP_S = 2.0
SLOW_METADATA_S = 20.0
THROTTLE_SIGNALS = frozenset({"rate-limited", "bot-check"})


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _rate(num: float, secs: float) -> float | None:
    return round(num / secs, 1) if secs > 0 else None


def _row(vid: str, out: Any, calls: list[dict]) -> dict:
    meta = [c for c in calls if c["step"] == "metadata"]
    caps = [c for c in calls if c["step"] == "captions"]
    cap_bytes = sum(len(i.text.encode("utf-8")) for i in out.items if i.kind == "transcript")
    cap_s = sum(c["elapsed_s"] for c in caps)
    return {
        "video": vid, "ok": out.error is None, "error_code": out.error_code,
        "throttled": bool(out.throttled), "bot_check": out.bot_check,
        "metadata_s": round(sum(c["elapsed_s"] for c in meta), 3), "metadata_calls": len(meta),
        "caption": out.caption, "caption_s": round(cap_s, 3), "caption_bytes": cap_bytes,
        "caption_bytes_per_s": _rate(cap_bytes, cap_s),
    }


def verdict(rows: list[dict]) -> tuple[str, str]:
    """The probe verdict and the plain reason for it."""
    signals = [r for r in rows if r["throttled"] or r["error_code"] in THROTTLE_SIGNALS or r["bot_check"]]
    if signals:
        return "throttled", f"{len(signals)} of {len(rows)} probe video(s) met a rate limit or a bot check"
    if rows and not any(r["ok"] for r in rows):
        return "failing", f"no probe video could be read ({rows[0]['error_code']})"
    med = _median([r["metadata_s"] for r in rows if r["ok"]])
    if med is not None and med > SLOW_METADATA_S:
        return "throttled", f"median metadata call took {med}s (limit {SLOW_METADATA_S}s)"
    return "ok", "every probe video answered without a throttle signal"


def run_probe(timed: TimedRunner, gather: Callable[[str], Any], *, videos: Sequence[str] = PROBE_VIDEOS,
              gap_s: float = MIN_GAP_S, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Probe the yt-dlp path. ``gather`` is a yt-dlp source's ``gather`` built on ``timed``."""
    if gap_s < MIN_GAP_S:
        raise ValueError(f"the probe waits at least {MIN_GAP_S}s between videos, got {gap_s}")
    rows = []
    for n, vid in enumerate(videos):
        if n:
            sleep(gap_s)
        mark = timed.mark()
        out = gather(f"https://www.youtube.com/watch?v={vid}")
        rows.append(_row(vid, out, timed.since(mark)))
    meta_s = [r["metadata_s"] for r in rows if r["ok"]]
    total_meta = sum(meta_s)
    name, reason = verdict(rows)
    return {
        "schema": PROBE_SCHEMA, "path": "yt-dlp", "verdict": name, "reason": reason,
        "videos": rows, "gap_s": gap_s,
        "median_metadata_s": _median(meta_s),
        "metadata_calls_per_min": round(len(meta_s) * 60.0 / total_meta, 2) if total_meta > 0 else None,
        "media_download": "not in scope: gather never downloads video or audio streams",
    }
