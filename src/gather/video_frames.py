"""The frame stage of a video bundle: fetch the storyboard sprite images a plan needs, then
write the contact sheets and say in the bundle's record what they are.

``fetch_frames`` is the live edge. It asks for each sprite image once through Gather's own
fetch (public addresses only, Gather's own User-Agent, no cookies), spaced by a ``HostLimiter``.
Any answer but 200 ends the stage there: a refusal is recorded and never retried, and the
sheets are cut from what arrived. ``frame_record`` is pure of the network.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from gather.frame_sheets import NEEDS, available, write_sheets
from gather.pacing import HostLimiter
from gather.storyboard import Frame, Level, best_level, plan_frames

SOURCE = "site preview storyboard"
NONE_OFFERED = "none offered"
SKIPPED = "skipped (--no-frames)"
MAX_SPRITE_BYTES = 8 << 20

# (address) -> (HTTP status, body)
Fetcher = Callable[[str], tuple[int, bytes]]


@dataclass(slots=True)
class FrameFetch:
    level: Level
    plan: list[Frame]
    blobs: dict[int, bytes] = field(default_factory=dict)
    error: str | None = None


def http_fetcher(url: str) -> tuple[int, bytes]:
    from gather.fetch import fetch

    receipt, body = fetch(url, timeout=20.0, max_bytes=MAX_SPRITE_BYTES, retries=1)
    return receipt.status, body or b""


def fetch_frames(info: dict, *, fetcher: Fetcher | None = None, limiter: HostLimiter | None = None,
                 stop: threading.Event | None = None) -> FrameFetch | None:
    """The sprite images for an even spread of frames, or None when the info lists no
    storyboard. ``stop`` ends the loop early (the bundle failed elsewhere)."""
    from gather.fetch import FetchError

    level = best_level(info)
    if level is None:
        return None
    get, pace = fetcher or http_fetcher, limiter or HostLimiter(1.0)
    got = FrameFetch(level, plan_frames(level))
    for frag in sorted({f.fragment for f in got.plan}):
        if stop is not None and stop.is_set():
            got.error = "stopped: the bundle ended before every sprite image was read"
            break
        url = level.urls[frag]
        pace.wait(url)
        try:
            status, body = get(url)
        except (FetchError, ValueError, OSError) as exc:
            got.error = f"sprite image {frag + 1} of {len(level.urls)}: {exc}"
            break
        if status != 200 or not body:  # a refusal or a throttle: stop here, never ask again
            got.error = f"sprite image {frag + 1} of {len(level.urls)}: HTTP {status}"
            break
        got.blobs[frag] = body
    return got


def frame_record(out_dir: str, vid: str, got: FrameFetch | None, *, asked: bool = True) -> dict | str:
    """Write the sheets and return the ``frames`` value of the bundle's record: a dict when
    sheets were written, else one plain line that says why there are none."""
    if not asked:
        return SKIPPED
    if not available():
        return f"not cut: {NEEDS}"
    if got is None:
        return NONE_OFFERED
    if not got.blobs:
        return f"not fetched: {got.error or 'no sprite image arrived'}"
    made = write_sheets(out_dir, vid, got.level, got.plan, got.blobs)
    if not made["count"]:
        return f"not cut: no sprite image could be read ({got.error or 'unreadable image data'})"
    level = got.level
    return {
        "status": "ok" if got.error is None and not made["missing"] else "partial",
        "source": SOURCE, "level": level.format_id, "frame_px": [level.width, level.height],
        "note": (f"Frames are the site's preview thumbnails, {level.width} by {level.height} pixels each. "
                 "They are not full-resolution video frames, and no video file was downloaded."),
        "interval_s": round(level.interval, 3), "available": level.total, **made,
        "sprite_images": len(got.blobs), "error": got.error,
    }


def frames_line(rec: dict | str | None) -> str:
    """The frame stage in one line, for SOURCE.txt and the command's report."""
    if not isinstance(rec, dict):
        return f"frames: {rec or 'not requested'}"
    w, h = rec["frame_px"]
    return (f"{rec['count']} frames on {len(rec['sheets'])} contact sheets from the {SOURCE} "
            f"({w}x{h} pixel thumbnails)" + ("" if rec["status"] == "ok" else f", partial: {rec['error'] or 'frames missing'}"))
