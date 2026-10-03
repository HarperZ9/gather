"""The route record: which path served an item and how fast that path answered.

A source with more than one way to reach a platform (yt-dlp or the YouTube Data API, say)
stamps each item it returns with one ``RouteRecord`` under ``item.meta["route"]``. The record
names the channel, the path, whether a credential was used (present or absent, never the value),
why a fallback happened, and the measured cost of the calls that served the item: wall seconds,
requests and bytes, with the derived rates. The catalog row carries it, so a reader of the
receipt sees how each item was obtained and at what rate.

Pure: no network. The shape is ``gather.route/1``; other tools that read the same platforms can
mirror it field for field.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from gather.item import Item

ROUTE_SCHEMA = "gather.route/1"
AUTH_STATES = ("absent", "present")


@dataclass(frozen=True, slots=True)
class RouteRecord:
    """One serving path's record. ``elapsed_s``, ``requests`` and ``bytes`` cover only the calls
    that produced the item, so a failed first path is described by ``fallback_reason``, not mixed
    into the rate. ``extra`` holds path-specific counters (a quota cost, a remaining-requests
    header), never a credential."""

    channel: str
    path: str
    elapsed_s: float
    requests: int
    bytes: int
    auth: str = "absent"
    fallback_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.auth not in AUTH_STATES:
            raise ValueError(f"auth must be one of {AUTH_STATES}, got {self.auth!r}")
        if self.elapsed_s < 0 or self.requests < 0 or self.bytes < 0:
            raise ValueError("elapsed_s, requests and bytes must be 0 or more")

    def rates(self) -> dict[str, float | None]:
        """Bytes per second and requests per minute, or None when no time was measured."""
        if self.elapsed_s <= 0:
            return {"bytes_per_s": None, "requests_per_min": None}
        return {"bytes_per_s": round(self.bytes / self.elapsed_s, 1),
                "requests_per_min": round(self.requests * 60.0 / self.elapsed_s, 2)}

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": ROUTE_SCHEMA, "channel": self.channel, "path": self.path, "auth": self.auth,
            "elapsed_s": round(self.elapsed_s, 3), "requests": self.requests, "bytes": self.bytes,
            **self.rates(),
        }
        if self.fallback_reason:
            out["fallback_reason"] = self.fallback_reason
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


def stamp(items: list[Item], record: RouteRecord) -> list[Item]:
    """Copies of ``items`` with ``meta["route"]`` set to ``record``. The receipt's sha256
    fingerprints the text only, so stamping leaves every content hash as it was."""
    route = record.to_dict()
    return [dataclasses.replace(i, meta={**i.meta, "route": route}) for i in items]


def route_of(item: Item) -> dict[str, Any] | None:
    """The route record on an item, or None when its source has only one path."""
    value = item.meta.get("route")
    return value if isinstance(value, dict) else None
