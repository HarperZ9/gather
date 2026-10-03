"""YouTube intake with yt-dlp as the primary path and the Data API as a keyed fallback.

``YouTubeRoute`` runs the yt-dlp source first, every time. It turns to the official Data API
only when both hold:

- the user set their own key (``GATHER_YOUTUBE_API_KEY`` by default), and
- yt-dlp was throttled or failed for a reason that is about the path, not the video: a rate
  limit, a bot check, a timeout, a missing or refused tool, or an error.

A verdict about the video itself (private, removed, members-only, age-restricted, geo-blocked,
upcoming) never triggers the fallback: the API would only repeat it. A bot check ends the yt-dlp
attempt as before (no retry, no workaround); the fallback then reads the video's public metadata
through the official API, the documented route for that.

Every item comes back stamped with a ``gather.route/1`` record (see gather.route): the path that
served it, the wall seconds, requests and bytes of the serving calls, and the derived rates. The
fallback path also records the reason yt-dlp could not serve the item. Requests stay at a single
user's pace: one call at a time, the yt-dlp source's own backoff, no proxy and no identity change.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gather.credentials import MissingCredential, has_secret
from gather.item import Item
from gather.route import RouteRecord, stamp
from gather.video_source import VideoOutcome, VideoSource
from gather.youtube_api import KEY_ENV, QUOTA_PER_CALL, DataApiClient, video_id
from gather.ytdlp import CallResult, Runner

CHANNEL = "youtube"
YTDLP_PATH = "yt-dlp"
API_PATH = "youtube-data-api"

# yt-dlp failure codes that say the path is throttled or broken. Anything else is a verdict
# about the video and stands.
FALLBACK_CODES = frozenset({"rate-limited", "bot-check", "timeout", "tool-missing", "tool-refused",
                            "error", "bad-json", "forbidden", "no-formats"})

API_CAPTION_REASON = "api-no-captions"
API_CAPTION_DETAIL = ("the Data API serves caption text only for videos the key's owner can edit; "
                      "the transcript was not fetched on this path")


class TimedRunner:
    """Wraps a yt-dlp runner and records each call's wall seconds and output bytes."""

    def __init__(self, runner: Runner | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._runner = runner
        self._clock = clock
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], timeout: float) -> CallResult:
        # no runner given: the video source module's runner, read at call time, so there is one
        # place to replace it
        from gather import video_source

        start = self._clock()
        result = (self._runner or video_source.subprocess_runner)(argv, timeout)
        self.calls.append({"elapsed_s": max(0.0, self._clock() - start),
                           "bytes": len(result.stdout.encode("utf-8")), "ok": result.ok,
                           "step": _step(argv)})
        return result

    def mark(self) -> int:
        return len(self.calls)

    def since(self, mark: int) -> list[dict[str, Any]]:
        return self.calls[mark:]


def _step(argv: list[str]) -> str:
    if "--flat-playlist" in argv:
        return "listing"
    return "captions" if "--load-info-json" in argv else "metadata"


@dataclass(slots=True)
class RoutedOutcome:
    """A video outcome plus the route that served it (None when nothing served it)."""

    outcome: VideoOutcome
    route: RouteRecord | None = None
    notes: list[str] = field(default_factory=list)


def fallback_wanted(out: VideoOutcome) -> bool:
    """True when yt-dlp served no items for a reason about the path, not the video."""
    return out.error is not None and (out.throttled or (out.error_code or "") in FALLBACK_CODES)


class YouTubeRoute:
    """One video in, items out; yt-dlp first, the Data API only as the keyed fallback.

    ``api`` is the fallback client, or None to turn the fallback off. ``source_factory`` builds
    the yt-dlp source around the timed runner, so tests hand in a fake runner."""

    name = "video"

    def __init__(self, *, source_factory: Callable[[Runner], VideoSource] | None = None,
                 runner: Runner | None = None, api: DataApiClient | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 log: Callable[[str], None] | None = None) -> None:
        self._timed = TimedRunner(runner, clock)
        self._wall = wall
        self._source = (source_factory or (lambda r: VideoSource(runner=r)))(self._timed)
        self._api = api
        self._log = log or (lambda msg: print(msg, file=sys.stderr))

    def fetch(self, target: str) -> list[Item]:
        routed = self.gather(target)
        if routed.outcome.error is not None:
            raise RuntimeError(routed.outcome.error)
        return list(routed.outcome.items)

    def gather(self, target: str) -> RoutedOutcome:
        mark = self._timed.mark()
        out = self._source.gather(target)
        if out.error is None:
            calls = self._timed.since(mark)
            record = RouteRecord(CHANNEL, YTDLP_PATH, sum(c["elapsed_s"] for c in calls), len(calls),
                                 sum(c["bytes"] for c in calls) + _transcript_bytes(out.items))
            out.items = stamp(out.items, record)
            return RoutedOutcome(out, record)
        if not fallback_wanted(out) or self._source.captions == "only":
            return RoutedOutcome(out)  # a verdict about the video, or a pass the API cannot serve
        if self._api is None or not has_secret(self._api.key_env):
            note = (f"yt-dlp could not serve {target} ({out.error_code}); set {KEY_ENV} to your own "
                    f"Data API key to let gather read its metadata through the official API")
            self._log(f"gather: {note}")
            return RoutedOutcome(out, notes=[note])
        return self._fallback(target, out)

    def _fallback(self, target: str, out: VideoOutcome) -> RoutedOutcome:
        from gather.video import items_from_info

        reason = f"{out.error_code}: {out.error}"[:300]
        vid = video_id(target)
        if vid is None:
            return RoutedOutcome(out, notes=["the Data API fallback needs a single-video URL or id"])
        assert self._api is not None
        try:
            got = self._api.fetch_info(vid)
        except (MissingCredential, LookupError, ValueError, OSError) as exc:
            out.error = f"{out.error} | Data API fallback failed: {str(exc)[:200]}"
            return RoutedOutcome(out)
        record = RouteRecord(CHANNEL, API_PATH, got.elapsed_s, 1, got.bytes, auth="present",
                             fallback_reason=reason, extra={"quota_units": QUOTA_PER_CALL})
        items = [i for i in items_from_info(got.info, None, fetched_at=float(self._wall()), method=API_PATH)
                 if i.kind == "metadata"]
        out.items = stamp(items, record)
        out.video_id, out.title = vid, str(got.info.get("title", ""))
        out.error, out.error_code = None, None
        out.caption, out.caption_reason, out.caption_detail = "missing", API_CAPTION_REASON, API_CAPTION_DETAIL
        self._log(f"gather: yt-dlp could not serve {vid} ({reason[:80]}); metadata read through the Data API")
        return RoutedOutcome(out, record)


def _transcript_bytes(items: list[Item]) -> int:
    """Caption text bytes: yt-dlp writes the track to a file, so it is not in the call output."""
    return sum(len(i.text.encode("utf-8")) for i in items if i.kind == "transcript")
