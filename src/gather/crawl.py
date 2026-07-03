"""Crawl + map: a competitive crawler that also witnesses what it did.

Capability first (the reason a user would pick it): concurrent fetching, a
BFS/DFS frontier, URL canonicalization and dedup, robots.txt compliance, sitemap
discovery, depth and page caps, per-host throttling, and pause/resume via a
serializable state. That is crawlee/firecrawl-class crawl orchestration.

Then the multiplier none of them carry: an append-only, hash-chained crawl
ledger. Each record links to the previous by hash, so a reviewer can re-derive
the chain and prove the crawl was not reordered, truncated, or edited after the
fact. Capability makes it worth using; the ledger makes it trustworthy.

The fetcher is a seam, so the whole orchestration is tested offline with a fake
fetcher; the real fetcher wraps [fetch.py] and [dom.py]. Pure except the injected
fetcher/clock/sleep.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from gather.dom import parse_dom, select
from gather.item import content_hash

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
DEFAULT_UA_NAME = "gather"


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    final_url: str
    status: int
    html: str


def default_canonicalize(url: str) -> str:
    """Lowercase scheme/host, drop the fragment, normalize default ports and an
    empty path. Keeps the query (it can be semantically load-bearing)."""
    p = urlsplit(url)
    scheme = (p.scheme or "http").lower()
    host = (p.hostname or "").lower()
    netloc = host
    if p.port and not ((scheme == "http" and p.port == 80) or (scheme == "https" and p.port == 443)):
        netloc = f"{host}:{p.port}"
    return urlunsplit((scheme, netloc, p.path or "/", p.query, ""))


def _in_scope(url: str, allowed_hosts: set[str]) -> bool:
    p = urlsplit(url)
    return p.scheme in ("http", "https") and (p.hostname or "").lower() in allowed_hosts


def extract_links(html: str, base: str, allowed_hosts: set[str], canon: Callable[[str], str]) -> list[str]:
    """In-scope, canonical, de-duplicated links from a page. Pure."""
    out: list[str] = []
    seen: set[str] = set()
    for a in select(parse_dom(html), "a"):
        href = a.attrs.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absu = urljoin(base, href)
        if not absu.lower().startswith(("http://", "https://")):
            continue
        cu = canon(absu)
        if cu not in seen and _in_scope(cu, allowed_hosts):
            seen.add(cu)
            out.append(cu)
    return out


def _sitemap_urls(fetcher, seed: str, canon: Callable[[str], str]) -> list[str]:
    p = urlsplit(seed)
    sm = urlunsplit((p.scheme, p.netloc, "/sitemap.xml", "", ""))
    try:
        page = fetcher(sm)
    except Exception:
        return []
    return [canon(u) for u in _LOC.findall(page.html)] if page.status == 200 else []


def make_robots(fetcher, ua: str = DEFAULT_UA_NAME) -> Callable[[str], bool]:
    """A per-host robots.txt policy backed by the fetcher. Missing/unreadable
    robots means allow (the conventional default)."""
    cache: dict[tuple[str, str], urllib.robotparser.RobotFileParser] = {}

    def allowed(url: str) -> bool:
        p = urlsplit(url)
        key = (p.scheme, p.netloc)
        rp = cache.get(key)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                page = fetcher(urlunsplit((p.scheme, p.netloc, "/robots.txt", "", "")))
                rp.parse(page.html.splitlines() if page.status == 200 else [])
            except Exception:
                rp.parse([])
            cache[key] = rp
        return rp.can_fetch(ua, url)

    return allowed


@dataclass(frozen=True, slots=True)
class CrawlRecord:
    url: str
    final_url: str
    status: int
    depth: int
    content_sha256: str
    discovered_from: str
    fetched_at: float
    entry_hash: str


def _core(rec: dict) -> dict:
    return {k: rec[k] for k in (
        "url", "final_url", "status", "depth", "content_sha256", "discovered_from", "fetched_at")}


def _entry_hash(prev: str, core: dict) -> str:
    return hashlib.sha256((prev + json.dumps(core, sort_keys=True)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CrawlLedger:
    """Append-only, hash-chained record of the crawl. Tamper-evident."""

    records: tuple[CrawlRecord, ...]
    root_hash: str

    def verify(self) -> bool:
        prev = ""
        for r in self.records:
            core = _core({
                "url": r.url, "final_url": r.final_url, "status": r.status, "depth": r.depth,
                "content_sha256": r.content_sha256, "discovered_from": r.discovered_from,
                "fetched_at": r.fetched_at})
            if _entry_hash(prev, core) != r.entry_hash:
                return False
            prev = r.entry_hash
        return prev == self.root_hash


@dataclass(slots=True)
class CrawlState:
    """Resumable frontier + visited set + ledger records so a crawl can pause and
    continue with an unbroken hash chain."""

    frontier: list[list] = field(default_factory=list)   # [url, depth, parent]
    visited: list[str] = field(default_factory=list)
    records: list[CrawlRecord] = field(default_factory=list)


@dataclass(slots=True)
class CrawlResult:
    ledger: CrawlLedger
    state: CrawlState
    pages: int
    map: list[str]


def _pop(frontier: list, strategy: str):
    return frontier.pop(0) if strategy == "bfs" else frontier.pop()


def _fetch_one(fetcher, url, throttle, last_host, sleep, clock):
    if throttle > 0:
        host = urlsplit(url).hostname or ""
        wait = throttle - (clock() - last_host.get(host, -1e18))
        if wait > 0:
            sleep(wait)
        last_host[host] = clock()
    try:
        return fetcher(url)
    except Exception:
        return None


def _fetch_batch(fetcher, batch, workers, throttle, last_host, sleep, clock):
    if workers > 1 and throttle <= 0:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pages = list(ex.map(lambda it: _safe(fetcher, it[0]), batch))
        return list(zip(batch, pages))
    return [(it, _fetch_one(fetcher, it[0], throttle, last_host, sleep, clock)) for it in batch]


def _safe(fetcher, url):
    try:
        return fetcher(url)
    except Exception:
        return None


def crawl(
    seeds, *,
    fetcher: Callable[[str], FetchedPage],
    max_depth: int = 2,
    max_pages: int = 50,
    workers: int = 1,
    strategy: str = "bfs",
    allowed_hosts: set[str] | None = None,
    obey_robots: bool = True,
    robots: Callable[[str], bool] | None = None,
    include_sitemap: bool = False,
    throttle: float = 0.0,
    ua: str = DEFAULT_UA_NAME,
    canonicalize: Callable[[str], str] = default_canonicalize,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    resume_from: CrawlState | None = None,
) -> CrawlResult:
    """Crawl from ``seeds`` and return a result whose ledger is re-verifiable."""
    seeds = [canonicalize(s) for s in seeds]
    hosts = set(allowed_hosts) if allowed_hosts else {urlsplit(s).hostname or "" for s in seeds}
    check = robots if robots is not None else (make_robots(fetcher, ua) if obey_robots else (lambda _u: True))

    if resume_from is not None:
        visited = set(resume_from.visited)
        frontier = [list(f) for f in resume_from.frontier]
        records = list(resume_from.records)
    else:
        visited, records = set(), []
        frontier = [[s, 0, ""] for s in seeds]
        if include_sitemap:
            frontier += [[u, 0, "sitemap"] for s in seeds for u in _sitemap_urls(fetcher, s, canonicalize)
                         if _in_scope(u, hosts)]
    prev = records[-1].entry_hash if records else ""
    last_host: dict[str, float] = {}
    pages = len(records)

    while frontier and pages < max_pages:
        batch: list[tuple[str, int, str]] = []
        while frontier and len(batch) < max(1, workers) and pages + len(batch) < max_pages:
            url, depth, parent = _pop(frontier, strategy)
            if url in visited or depth > max_depth:
                continue
            visited.add(url)
            if check(url):
                batch.append((url, depth, parent))
        for (url, depth, parent), page in sorted(
            _fetch_batch(fetcher, batch, workers, throttle, last_host, sleep, clock),
            key=lambda t: t[0][0],
        ):
            if page is None:
                continue
            core = _core({
                "url": page.url, "final_url": page.final_url, "status": page.status, "depth": depth,
                "content_sha256": content_hash(page.html), "discovered_from": parent,
                "fetched_at": float(clock())})
            prev = _entry_hash(prev, core)
            records.append(CrawlRecord(**core, entry_hash=prev))
            pages += 1
            if depth < max_depth:
                for link in extract_links(page.html, page.final_url, hosts, canonicalize):
                    if link not in visited:
                        frontier.append([link, depth + 1, url])

    ledger = CrawlLedger(tuple(records), prev)
    state = CrawlState([list(f) for f in frontier], sorted(visited), records)
    return CrawlResult(ledger=ledger, state=state, pages=pages, map=[r.url for r in records])
