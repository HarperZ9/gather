"""Dev-mode response cache: fetch once, iterate your parser offline.

Scrapling's dev mode caches a response so you can rebuild extraction without
re-scraping. gather does that and keeps it honest: each cached body is stored
content-addressed, so a replay is verifiably the same bytes that were fetched,
and a revalidation (conditional GET with the stored ETag / Last-Modified) that
returns 304 serves the cached body rather than silently refetching.

    cached_fetch(url, cache=c)                 -> replay from cache if present
    cached_fetch(url, cache=c, revalidate=True) -> conditional GET; 304 -> cache

Pure except the injected fetch function and clock; the store is a plain directory
of ``<key>.json`` + ``<key>.body`` pairs, so it is inspectable and portable.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheEntry:
    url: str
    status: int
    content_sha256: str
    etag: str
    last_modified: str
    fetched_at: float


@dataclass(frozen=True, slots=True)
class CachedResult:
    url: str
    source: str          # "cache" | "network" | "cache-revalidated"
    status: int
    content_sha256: str


class ResponseCache:
    """A content-addressed on-disk response cache."""

    def __init__(self, root) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        return self.root / f"{key}.json", self.root / f"{key}.body"

    def get(self, url: str) -> tuple[CacheEntry, bytes] | None:
        meta_p, body_p = self._paths(url)
        if not (meta_p.exists() and body_p.exists()):
            return None
        entry = CacheEntry(**json.loads(meta_p.read_text(encoding="utf-8")))
        return entry, body_p.read_bytes()

    def put(self, url: str, *, status: int, body: bytes, etag: str = "",
            last_modified: str = "", fetched_at: float | None = None) -> CacheEntry:
        meta_p, body_p = self._paths(url)
        entry = CacheEntry(
            url=url, status=status, content_sha256=_sha(body), etag=etag,
            last_modified=last_modified,
            fetched_at=float(fetched_at if fetched_at is not None else time.time()),
        )
        body_p.write_bytes(body)
        meta_p.write_text(json.dumps(asdict(entry), sort_keys=True), encoding="utf-8")
        return entry

    def conditional(self, url: str) -> tuple[str | None, str | None]:
        got = self.get(url)
        if not got:
            return None, None
        entry, _ = got
        return (entry.etag or None), (entry.last_modified or None)

    def verify(self, url: str) -> bool:
        got = self.get(url)
        if not got:
            return False
        entry, body = got
        return _sha(body) == entry.content_sha256


def cached_fetch(
    url: str, *,
    cache: ResponseCache,
    fetch_fn: Callable | None = None,
    revalidate: bool = False,
    clock: Callable[[], float] = time.time,
    **fetch_kw,
) -> tuple[CachedResult, bytes | None]:
    """Return ``(result, body)``. Replays from cache unless ``revalidate`` (then a
    conditional GET is made; a 304 still serves the cached body)."""
    if fetch_fn is None:
        from gather.fetch import fetch  # lazy: keeps cache.py network-free to import
        fetch_fn = fetch
    cached = cache.get(url)
    if cached and not revalidate:
        entry, body = cached
        return CachedResult(url, "cache", entry.status, entry.content_sha256), body

    etag, last_modified = cache.conditional(url) if cached else (None, None)
    receipt, fetched_body = fetch_fn(url, etag=etag, last_modified=last_modified, **fetch_kw)
    if receipt.not_modified and cached:
        entry, cbody = cached
        return CachedResult(url, "cache-revalidated", entry.status, entry.content_sha256), cbody
    if receipt.not_modified:
        # 304 with no cache entry to revalidate against: we sent no validators, so
        # the server broke the conditional-request contract. There is no body to
        # store; refuse rather than poison the content-addressed cache with b"".
        raise ValueError(f"received 304 for {url} with no cache entry to revalidate")
    entry = cache.put(
        url, status=receipt.status, body=fetched_body or b"", etag=receipt.etag,
        last_modified=receipt.last_modified, fetched_at=float(clock()),
    )
    return CachedResult(url, "network", entry.status, entry.content_sha256), fetched_body
