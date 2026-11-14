"""Preview storyboards: which frames to take, and where each one sits. Pure of the network.

A video site publishes storyboards for the scrub bar: sprite images, each a grid of small
thumbnails taken at a fixed interval across the whole video. yt-dlp lists them in the info it
already returns as formats named ``sb0``, ``sb1`` and so on, each with its fragment addresses,
grid (``rows`` by ``columns``), thumbnail size and frame rate. So frames across a video cost a
few small image requests and no video download.

``best_level`` picks the level with the largest thumbnails. ``plan_frames`` chooses 24 to 96
frames evenly across the duration and holds the number of sprite images to fetch under a cap,
so a long video costs no more requests than a short one. A storyboard thumbnail is small
(320 by 180 pixels at best on YouTube): the plan and the manifest carry its real size.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_FRAMES = 24
MAX_FRAMES = 96
MAX_FRAGMENTS = 24
_STEPS = (96, 84, 72, 60, 48, 36, 30, 24)


@dataclass(frozen=True, slots=True)
class Level:
    """One storyboard level: ``total`` thumbnails of ``width`` by ``height`` pixels, ``per`` to a
    sprite image (``rows`` by ``columns``), one every ``interval`` seconds."""

    format_id: str
    width: int
    height: int
    rows: int
    columns: int
    interval: float
    total: int
    urls: tuple[str, ...]

    @property
    def per(self) -> int:
        return self.rows * self.columns


@dataclass(frozen=True, slots=True)
class Frame:
    """One chosen thumbnail: its number in the level, the second it stands for, and its place
    (``fragment``, ``row``, ``column``) in the sprite images."""

    index: int
    time: float
    fragment: int
    row: int
    column: int


def _positive(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _level(fmt: dict, duration: float) -> Level | None:
    width, height = int(_positive(fmt.get("width"))), int(_positive(fmt.get("height")))
    rows, columns = int(_positive(fmt.get("rows"))), int(_positive(fmt.get("columns")))
    fragments = [f for f in fmt.get("fragments") or [] if isinstance(f, dict) and f.get("url")]
    if not (width and height and rows and columns and fragments):
        return None
    per, fps = rows * columns, _positive(fmt.get("fps"))
    # every sprite image is full but the last; its share of the time gives its thumbnail count
    last = round(_positive(fragments[-1].get("duration")) * fps) if fps else per
    total = (len(fragments) - 1) * per + min(per, max(1, last))
    interval = 1 / fps if fps else (duration / total if duration else 0.0)
    return Level(str(fmt.get("format_id") or "sb"), width, height, rows, columns, interval, total,
                 tuple(str(f["url"]) for f in fragments))


def storyboard_levels(info: dict) -> list[Level]:
    """Every usable storyboard level in yt-dlp's info, largest thumbnails first."""
    duration = _positive(info.get("duration"))
    found = []
    for fmt in info.get("formats") or []:
        if isinstance(fmt, dict) and (fmt.get("format_note") == "storyboard" or str(fmt.get("format_id", "")).startswith("sb")):
            level = _level(fmt, duration)
            if level is not None:
                found.append(level)
    return sorted(found, key=lambda lv: (-lv.width * lv.height, -lv.total, lv.format_id))


def best_level(info: dict) -> Level | None:
    """The level with the largest thumbnails, or None when the site offers no storyboard."""
    levels = storyboard_levels(info)
    return levels[0] if levels else None


def _evenly(level: Level, count: int) -> list[Frame]:
    out = []
    for k in range(count):
        i = min(level.total - 1, int((k + 0.5) * level.total / count))
        frag, at = divmod(i, level.per)
        out.append(Frame(i, round(i * level.interval, 3), frag, at // level.columns, at % level.columns))
    return out


def plan_frames(level: Level, *, min_frames: int = MIN_FRAMES, max_frames: int = MAX_FRAMES,
                max_fragments: int = MAX_FRAGMENTS) -> list[Frame]:
    """24 to 96 thumbnails spread evenly across the video, in time order.

    The largest count is taken whose thumbnails sit in ``max_fragments`` sprite images or fewer.
    A level with fewer thumbnails than ``min_frames`` gives all it has."""
    if level.total <= min_frames:
        return _evenly(level, level.total)
    for count in (c for c in _STEPS if min_frames <= c <= max_frames):
        plan = _evenly(level, min(count, level.total))
        if len({f.fragment for f in plan}) <= max_fragments:
            return plan
    return _evenly(level, max(1, min(max_fragments, level.total)))
