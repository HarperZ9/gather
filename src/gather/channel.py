"""Channel and playlist intake: list every entry, then gather each into a corpus.

Listing uses yt-dlp's ``--flat-playlist`` per channel tab (videos, shorts, streams), which
names each upload without resolving it. Gathering runs one ``VideoSource`` pass per entry on a
small thread pool (default 2), with a shared ``Pacer`` spacing entry starts. Every entry's
outcome is appended to the pass ledger as it finishes, so an interrupted run resumes where it
stopped. When an entry spends its whole backoff budget still throttled, the run stops starting
new entries and records each remaining one as stopped, with the reason, instead of pressing on.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from gather.channel_ledger import append_row, needs_captions
from gather.pacing import Pacer
from gather.video_source import VideoOutcome, VideoSource

TABS = ("videos", "shorts", "streams")
_TAB_SUFFIX = re.compile(r"/(?:videos|shorts|streams|featured|playlists|community|about|live|releases|podcasts)$")


def is_playlist_url(url: str) -> bool:
    parts = urlsplit(url)
    return "list=" in parts.query or parts.path.rstrip("/").endswith("/playlist")


def tab_urls(url: str, tabs: Sequence[str] = TABS) -> list[tuple[str, str]]:
    """``(tab, url)`` pairs to list. A playlist URL is listed as is, under the tab ``playlist``;
    a channel URL (with or without a tab suffix) gets one URL per requested tab."""
    unknown = [t for t in tabs if t not in TABS]
    if unknown:
        raise ValueError(f"unknown channel tab(s): {', '.join(unknown)}; choose from {', '.join(TABS)}")
    if is_playlist_url(url):
        return [("playlist", url)]
    base = _TAB_SUFFIX.sub("", url.split("?", 1)[0].split("#", 1)[0].rstrip("/"))
    return [(tab, f"{base}/{tab}") for tab in tabs]


def _entry_url(entry: dict, vid: str) -> str:
    for key in ("url", "webpage_url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    if entry.get("ie_key") == "Youtube":
        return f"https://www.youtube.com/watch?v={vid}"
    return str(entry.get("url") or vid)


def parse_listing(text: str, tab: str) -> list[dict]:
    """Entries from a ``--flat-playlist --dump-single-json`` document. Pure. Nested playlists
    are walked; links to other tabs or playlists are not entries and are skipped."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid yt-dlp listing JSON: {exc}") from exc
    out: list[dict] = []

    def walk(node: dict) -> None:
        for e in node.get("entries") or []:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("entries"), list):
                walk(e)
                continue
            if str(e.get("ie_key") or "").endswith(("Tab", "Playlist")):
                continue
            vid = str(e.get("id") or "")
            if vid:
                out.append({"id": vid, "url": _entry_url(e, vid), "title": str(e.get("title") or ""),
                            "tab": tab})

    if isinstance(doc, dict):
        walk(doc)
    return out


def merge_entries(per_tab: Sequence[list[dict]]) -> tuple[list[dict], int]:
    """Concatenate tab listings in order, keeping the first sighting of each id. Returns the
    unique entries and how many duplicates were dropped."""
    seen: set[str] = set()
    merged: list[dict] = []
    dupes = 0
    for entries in per_tab:
        for e in entries:
            if e["id"] in seen:
                dupes += 1
                continue
            seen.add(e["id"])
            merged.append(e)
    return merged, dupes


def list_channel(source: VideoSource, url: str, tabs: Sequence[str] = TABS) -> dict:
    """List each tab. A tab that fails (a channel with no streams tab, say) is recorded with
    its reason and listed as zero; the other tabs still count."""
    report: dict[str, dict] = {}
    listings: list[list[dict]] = []
    for tab, tab_url in tab_urls(url, tabs):
        res, out = source.list_entries(tab_url)
        info: dict = {"url": tab_url, "listed": 0, "retries": len([a for a in out.attempts if not a.get("final")])}
        if out.error is not None:
            info.update(error=out.error, code=out.error_code)
            listings.append([])
        else:
            try:
                entries = parse_listing(res.stdout, tab)
            except ValueError as exc:
                info.update(error=str(exc), code="bad-json")
                entries = []
            info["listed"] = len(entries)
            listings.append(entries)
        report[tab] = info
    entries, dupes = merge_entries(listings)
    return {"tabs": report, "entries": entries, "unique_entries": len(entries), "duplicates": dupes}


def outcome_row(out: VideoOutcome, entry: dict, pass_: str, stored: dict, at: float) -> dict:
    """One ledger row. Counts only: no comment text and no commenter names."""
    return {
        "id": entry["id"], "tab": entry["tab"], "pass": pass_, "at": round(at, 3),
        "status": "ok" if out.ok else "failed", "code": out.error_code, "reason": out.error,
        "caption": out.caption, "caption_lang": out.caption_lang,
        "caption_reason": out.caption_reason, "caption_detail": out.caption_detail or None,
        "comments": out.comments, "comment_count_reported": out.comment_count_reported,
        "items": len(out.items), "stored": stored,
        "retries": len([a for a in out.attempts if not a.get("final")]),
        "throttled": out.throttled, "attempts": out.attempts,
    }


def stopped_row(entry: dict, pass_: str, reason: str, at: float) -> dict:
    row = {"id": entry["id"], "tab": entry["tab"], "pass": pass_, "at": round(at, 3),
           "status": "stopped", "code": "stopped", "reason": reason, "caption": "skipped",
           "comments": 0, "items": 0, "retries": 0, "throttled": False, "attempts": []}
    if needs_captions(pass_):
        row.update(caption="missing", caption_reason="pass-stopped", caption_detail=reason)
    return row


@dataclass
class ChannelRun:
    """Gather ``entries`` with ``source`` into ``corpus``; append each outcome to ``ledger``."""

    source: VideoSource
    corpus: object  # a gather.store.Corpus (anything with add(items) -> dict)
    ledger: str
    pass_: str
    pacer: Pacer
    concurrency: int = 2
    max_throttled: int = 1
    clock: Callable[[], float] = time.time
    log: Callable[[str], None] = print
    rows: list[dict] = field(default_factory=list)
    stored: dict = field(default_factory=lambda: {"added": 0, "deduped": 0})
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.concurrency < 1 or self.max_throttled < 1:
            raise ValueError("concurrency and max_throttled must be >= 1")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._throttled = 0
        self._total = 0

    def run(self, entries: Sequence[dict]) -> list[dict]:
        self._total = len(entries)
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(self._one, entries))
        return self.rows

    def _one(self, entry: dict) -> None:
        if not self._stop.is_set():
            self.pacer.wait()
        if self._stop.is_set():
            self._record(stopped_row(entry, self.pass_, self.stop_reason or "pass stopped", self.clock()))
            return
        try:
            out = self.source.gather(entry["url"])
        except Exception as exc:  # recorded, never swallowed: the ledger and log both carry it
            out = VideoOutcome(target=entry["url"], error=f"gather raised: {exc!r}", error_code="exception")
        with self._lock:
            stored = self._store(out)
            row = outcome_row(out, entry, self.pass_, stored, self.clock())
            if out.throttled:
                self._throttled += 1
                if self._throttled >= self.max_throttled and not self._stop.is_set():
                    step = out.attempts[-1]["step"] if out.attempts else "a step"
                    self.stop_reason = (f"stopped after {entry['id']}: {step} still throttled after the "
                                        f"backoff budget ({self._throttled} entr{'y' if self._throttled == 1 else 'ies'})")
                    self._stop.set()
                    self.log(f"gather: {self.stop_reason}; remaining entries are recorded as stopped")
            self._append(row)

    def _store(self, out: VideoOutcome) -> dict:
        if not out.items:
            return {"added": 0, "deduped": 0}
        try:
            got = self.corpus.add(out.items)  # type: ignore[attr-defined]
        except Exception as exc:
            out.error, out.error_code = f"store failed: {exc}", "store-failed"
            self.log(f"gather: storing {out.video_id or out.target} failed: {exc}")
            return {"added": 0, "deduped": 0}
        self.stored["added"] += got["added"]
        self.stored["deduped"] += got["deduped"]
        return {"added": got["added"], "deduped": got["deduped"]}

    def _record(self, row: dict) -> None:
        with self._lock:
            self._append(row)

    def _append(self, row: dict) -> None:
        append_row(self.ledger, row)
        self.rows.append(row)
        cap = row.get("caption", "")
        if row.get("caption_lang"):
            cap += f"({row['caption_lang']})"
        elif row.get("caption_reason"):
            cap += f"({row['caption_reason']})"
        tail = f" {row['code']}: {str(row.get('reason') or '')[:160]}" if row["status"] != "ok" else ""
        self.log(f"[{len(self.rows)}/{self._total}] {row['id']} {row['tab']}: {row['status']} "
                 f"captions={cap} comments={row.get('comments', 0)} retries={row.get('retries', 0)}{tail}")
