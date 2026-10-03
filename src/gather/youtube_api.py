"""The YouTube Data API v3 fallback: video metadata with the user's own API key.

Gather reads YouTube through yt-dlp first. This module is the second path, used only when the
user has set their own key and yt-dlp is throttled or failing (see gather.youtube_route). It
reads one video's snippet, duration and public statistics with ``videos.list`` (1 quota unit
per call) and maps them onto the field names yt-dlp uses, so both paths produce the same
metadata item shape.

The Data API does not serve caption text for videos the key's owner cannot edit, so this path
yields metadata only, and the caller records the transcript as missing with that reason.

The key is read from the environment by name and sent in the ``X-Goog-Api-Key`` header. It never
reaches the request URL, an item, a receipt or a log line. ``video_id`` and ``info_from_api``
are pure; ``DataApiClient`` is the one network edge, and its HTTP call is injectable.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from gather.credentials import require_secret
from gather.net import http_get

KEY_ENV = "GATHER_YOUTUBE_API_KEY"
API_HOST = "www.googleapis.com"
VIDEOS_URL = f"https://{API_HOST}/youtube/v3/videos"
QUOTA_PER_CALL = 1  # videos.list, as published in the Data API quota table

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")

HttpGet = Callable[..., tuple[bytes, str]]


def video_id(target: str) -> str | None:
    """The 11-character video id in a watch, short, embed or youtu.be URL, or a bare id.
    None for anything else (a channel, a playlist, a search), which this path cannot serve."""
    value = (target or "").strip()
    if _ID.match(value):
        return value
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        query = urllib.parse.parse_qs(parts.query).get("v", [""])[0]
        segs = [s for s in parts.path.split("/") if s]
        candidate = query or (segs[1] if len(segs) > 1 and segs[0] in ("shorts", "embed", "live") else "")
    else:
        return None
    return candidate if _ID.match(candidate) else None


def iso_duration(value: object) -> int | None:
    """Seconds in an ISO 8601 duration such as ``PT1H2M3S``; None when it does not parse."""
    match = _DURATION.match(value) if isinstance(value, str) else None
    if not match or not any(match.groups()):
        return None
    d, h, m, s = (int(g) if g else 0 for g in match.groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def info_from_api(payload: str | bytes, vid: str) -> dict:
    """A yt-dlp-shaped info dict from a ``videos.list`` response. Raises LookupError when the
    response lists no such video and ValueError when it is not the expected JSON."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid Data API JSON: {exc}") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("the Data API response has no items list")
    match = next((i for i in items if isinstance(i, dict) and i.get("id") == vid), None)
    if match is None:
        raise LookupError(f"the Data API lists no public video {vid}")
    snippet = match.get("snippet") or {}
    stats = match.get("statistics") or {}
    published = str(snippet.get("publishedAt") or "")
    return {
        "id": vid,
        "title": str(snippet.get("title") or ""),
        "uploader": str(snippet.get("channelTitle") or ""),
        "duration": iso_duration((match.get("contentDetails") or {}).get("duration")),
        "upload_date": published[:10].replace("-", "") or None,
        "view_count": _int(stats.get("viewCount")),
        "comment_count": _int(stats.get("commentCount")),
        "webpage_url": f"https://www.youtube.com/watch?v={vid}",
    }


@dataclass(frozen=True, slots=True)
class ApiResult:
    info: dict
    elapsed_s: float
    bytes: int


class DataApiClient:
    """Reads one video's metadata from the Data API with the key named by ``key_env``."""

    def __init__(self, *, key_env: str = KEY_ENV, http: HttpGet = http_get,
                 clock: Callable[[], float] = time.monotonic, timeout: float = 20.0) -> None:
        self.key_env = key_env
        self._http = http
        self._clock = clock
        self._timeout = timeout

    def fetch_info(self, vid: str) -> ApiResult:
        key = require_secret(self.key_env)
        query = urllib.parse.urlencode({"part": "snippet,contentDetails,statistics", "id": vid})
        start = self._clock()
        body, _ctype = self._http(f"{VIDEOS_URL}?{query}", timeout=self._timeout,
                                  headers={"X-Goog-Api-Key": key})
        elapsed = max(0.0, self._clock() - start)
        return ApiResult(info_from_api(body, vid), elapsed, len(body))
