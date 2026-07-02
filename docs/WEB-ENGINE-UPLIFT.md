# gather web-data engine uplift

Make gather the accountable web-data engine that out-features and out-performs
browser-use, Scrapling, crawlee, and firecrawl, and wire its outputs as
first-class receipts into learn, forum, and index. The thesis is not to
out-muscle Playwright: it is that every scrape, crawl, and extraction gather
emits carries a re-verifiable receipt none of the four competitors produce.

## The competitors and the gap (verified 2026-07-02)

| Tool | Core strength | What it cannot prove |
| --- | --- | --- |
| browser-use | LLM-driven Playwright automation | that its output was not hallucinated |
| Scrapling | adaptive element relocation, TLS-impersonation fetch, ~2ms lxml parse | that a relocated element is still the right one |
| crawlee | persistent queue, proxy/session/fingerprint, autoscale | that a crawled page is unaltered |
| firecrawl | scrape to markdown, crawl, map, schema extract | which extracted field came from the page vs the model |

gather's wedge is the receipt: content hashes, selector-to-source-node
provenance, an enforced fetched-vs-inferred boundary, and drift verdicts that
make silent breakage visible.

## The persistent goal

```
/goal Make gather the accountable web-data engine that out-features and
out-performs browser-use, Scrapling, crawlee, and firecrawl, and wire its
outputs as first-class receipts into learn, forum, and index. Do NOT stop, wind
down, ask permission to continue, or declare done until every wedge below is
shipped as real, tested, zero-dep-core code (an optional browser backend is the
lone allowed edge), each on its own branch and PR-ready, each carrying a
re-verifiable receipt none of the four competitors can produce. After finishing
a wedge, immediately start the next in priority order. Only pause for a genuine
operator-only blocker (a secret, an external paid service, or a real design
fork); surface it in one line and continue on the next unblocked wedge. Advance
the gather-web-uplift progress marker each cycle.

Non-negotiables: zero core deps (stdlib only) with any browser strictly optional
and capability-gated; when a capability is missing, degrade to an honest
UNVERIFIABLE, never fake it; every wedge ships real tests with meaningful
assertions plus a must-fail negative fixture; no secrets, synthetic fixtures
only; no em-dashes in project text; honest scope labels; never merge without
operator authorization.

Wedges, in priority order (done = code + tests + negative fixture + README/USAGE
+ version bump + PR-ready):
  1. DOM + witnessable adaptive tracking + accountable extract.
  2. Accountable FETCH core: stdlib HTTP, browser-like headers, retry/backoff,
     conditional GET/ETag, redirect-chain provenance, a per-fetch receipt.
  3. CRAWL + MAP: frontier queue (BFS/DFS), URL canonicalization/dedup,
     robots.txt, sitemap discovery, per-host throttle, pause/resume checkpoint,
     append-only witnessed crawl ledger.
  4. STRUCTURED EXTRACT: schema-bound fields, each bound to a source node path +
     hash; a REJECT rule forbids any field value not present in fetched content.
  5. SELECTOR DRIFT MONITOR: saved selector + fingerprint re-checked on re-fetch,
     emitting a per-selector drift report with residuals.
  6. OPTIONAL BROWSER EDGE: pluggable, capability-gated backend for JS pages;
     absent means UNVERIFIABLE, never a faked render.
  7. PERF: benchmark parse/extract/select against the competitors' published
     numbers; publish honest results; where zero-dep cannot win raw speed, win on
     accountability and say so.
  8. INTEROP: gather crawl/corpus to index context-envelope + graph feed; gather
     extraction receipt to a forum evidence lane; gather selector-provenance
     receipt to a learn proof-lesson; each proven end-to-end on the organ-bundle
     spine.

Organically complete when wedges 2-8 are shipped and green, the three interop
demos pass end-to-end, USAGE/README are updated, the gather version is bumped,
and an honest benchmark table is published. Then, and only then, stop.
```

## Status

- Wedge 1: DONE on branch `feat/accountable-extract-track`.
  - `src/gather/dom.py` — zero-dep HTML DOM, stable node paths, CSS-lite `select`.
  - `src/gather/extract.py` — HTML to Markdown plus a re-verifiable `Extraction`
    receipt (content hash, per-block path + hash, fetched-vs-inferred `method`).
  - `src/gather/track.py` — `fingerprint` + `relocate` emitting the closed
    verdict set MATCH / RELOCATED / DRIFT / GONE with a residual.
  - Tests: `tests/test_dom.py`, `tests/test_extract.py`, `tests/test_track.py`
    (16 new; full suite 305 passed), including tamper and drift negatives.
- Wedge 2: DONE on the same branch.
  - `src/gather/fetch.py` — an accountable HTTP GET that reuses net.py's SSRF
    guard and cross-origin credential stripping, and returns a `FetchReceipt`
    (bytes hash, headers digest, recorded redirect chain, status, attempts) with
    conditional GET (ETag / If-Modified-Since, honest 304) and retry/backoff. The
    transport is a seam, so retry/conditional/receipt logic is tested offline.
  - Tests: `tests/test_fetch.py` (7; full suite 312 passed), including retry,
    exhaustion, tamper, and routing-header-guard negatives.
  - Honest limitation vs Scrapling: default UA identifies gather (no browser
    impersonation) and zero-dep cannot forge a TLS fingerprint; a caller may
    supply their own headers, on the record.
- Wedges 3 through 8: not started.
