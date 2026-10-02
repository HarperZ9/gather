"""monitor.py — scheduled re-fetch with change custody.

Firecrawl's headline monitor feature re-fetches a page set on a schedule and
alerts you it changed. gather does that and emits the receipt the alert can't:
a hash-chained ledger where every observation carries the content SHA it saw, so
"this page changed on this date" is a claim a third party re-derives by
re-fetching and re-comparing, not a notification you have to trust.

Per source, one pass yields exactly one closed verdict:

    NEW        first observation of this source (no prior baseline)
    UNCHANGED  server said 304, or the content SHA equals the baseline
    CHANGED    content SHA differs from the baseline (carries both SHAs)
    GONE       the resource is a hard 404/410
    ERROR      fetch failed or returned an unexpected status (transient/blocked)

Conditional requests: the stored etag / last-modified are sent, so an unchanged
page costs a 304 (no body, no re-hash) — cheaper than any full re-scrape.

The ledger is append-only and hash-chained with the SAME construction as the
crawl ledger (`_entry_hash`), so `verify()` catches any tampered or reordered
observation. State (the per-source baseline) and ledger are plain JSON.

Pure core: `monitor_pass` takes a fetch function and a clock, so the whole thing
is deterministic and offline-testable with a fake transport — no network in a
test, no wall clock in a receipt.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

VERDICTS = ("NEW", "UNCHANGED", "CHANGED", "GONE", "ERROR")
LEDGER_SCHEMA = "gather.monitor-ledger/1"
REPORT_SCHEMA = "gather.monitor-report/1"

# (receipt, body) — the shape gather.fetch.fetch returns
FetchFn = Callable[..., tuple[object, "bytes | None"]]


def _entry_hash(prev: str, core: dict) -> str:
    # identical construction to crawl._entry_hash: chain integrity composes
    return hashlib.sha256((prev + json.dumps(core, sort_keys=True)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Observation:
    url: str
    verdict: str
    at: float
    content_sha256: str          # "" when GONE/ERROR/304-unchanged-no-body
    prev_sha256: str             # the baseline this was compared against ("" for NEW)
    status: int
    entry_hash: str

    def as_dict(self) -> dict:
        return {"url": self.url, "verdict": self.verdict, "at": self.at,
                "content_sha256": self.content_sha256, "prev_sha256": self.prev_sha256,
                "status": self.status, "entry_hash": self.entry_hash}


def _core(url: str, verdict: str, at: float, sha: str, prev: str, status: int) -> dict:
    return {"url": url, "verdict": verdict, "at": at,
            "content_sha256": sha, "prev_sha256": prev, "status": status}


def _classify(url: str, prior: dict, fetch_fn: FetchFn) -> tuple[str, str, int]:
    """Fetch one source (conditionally if a baseline exists) and return
    (verdict, current_sha, status). Never raises: a failure is ERROR."""
    base_sha = prior.get("content_sha256", "")
    try:
        receipt, _body = fetch_fn(
            url,
            etag=prior.get("etag") or None,
            last_modified=prior.get("last_modified") or None,
        )
    except Exception:
        return ("ERROR", "", 0)
    status = getattr(receipt, "status", 0)
    if getattr(receipt, "not_modified", False):          # 304: server confirms unchanged
        return ("UNCHANGED", base_sha, status)
    if status in (404, 410):
        return ("GONE", "", status)
    if status >= 400 or status == 0:
        return ("ERROR", "", status)
    cur = getattr(receipt, "content_sha256", "")
    if not base_sha:
        return ("NEW", cur, status)
    if cur == base_sha:
        return ("UNCHANGED", cur, status)
    return ("CHANGED", cur, status)


def monitor_pass(sources: list[str], state: dict, fetch_fn: FetchFn, *,
                 clock: Callable[[], float]) -> tuple[dict, dict]:
    """One monitoring pass over `sources`. `state` is the prior baseline map
    (schema `gather.monitor-state/1`: {url: {content_sha256, etag, last_modified,
    fetched_at}} plus a `ledger` list). Returns (report, new_state).

    The report lists one Observation per source; the ledger grows append-only
    and hash-chained. Deterministic given `fetch_fn` and `clock`."""
    baselines = dict(state.get("baselines", {}))
    ledger = list(state.get("ledger", []))
    prev = ledger[-1]["entry_hash"] if ledger else ""
    at = clock()
    obs: list[Observation] = []
    counts = {v: 0 for v in VERDICTS}

    for url in sources:
        prior = baselines.get(url, {})
        verdict, cur_sha, status = _classify(url, prior, fetch_fn)
        counts[verdict] += 1
        core = _core(url, verdict, at, cur_sha, prior.get("content_sha256", ""), status)
        prev = _entry_hash(prev, core)
        o = Observation(url=url, verdict=verdict, at=at, content_sha256=cur_sha,
                        prev_sha256=prior.get("content_sha256", ""), status=status,
                        entry_hash=prev)
        obs.append(o)
        # update the baseline only when we actually observed content
        if verdict in ("NEW", "CHANGED"):
            baselines[url] = {"content_sha256": cur_sha, "fetched_at": at,
                              "etag": prior.get("etag", ""),
                              "last_modified": prior.get("last_modified", "")}
        elif verdict == "GONE":
            baselines.pop(url, None)

    ledger.extend(o.as_dict() for o in obs)
    new_state = {"schema": "gather.monitor-state/1", "baselines": baselines,
                 "ledger": ledger, "root_hash": prev}
    report = {"schema": REPORT_SCHEMA, "at": at, "sources": len(sources),
              "counts": counts,
              "changed": sorted(o.url for o in obs if o.verdict == "CHANGED"),
              "gone": sorted(o.url for o in obs if o.verdict == "GONE"),
              "errors": sorted(o.url for o in obs if o.verdict == "ERROR"),
              "observations": [o.as_dict() for o in obs],
              "recheck": "gather monitor --sources S --state STATE  (re-fetch and re-compare)"}
    return report, new_state


def verify_ledger(state: dict) -> bool:
    """Re-derive the whole chain; True iff every entry hash and the root match.
    A tampered SHA, a reordered observation, or a spliced entry breaks it."""
    prev = ""
    for e in state.get("ledger", []):
        core = _core(e["url"], e["verdict"], e["at"], e["content_sha256"],
                     e["prev_sha256"], e["status"])
        prev = _entry_hash(prev, core)
        if prev != e["entry_hash"]:
            return False
    return prev == state.get("root_hash", "")
