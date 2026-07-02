# gather web-data engine uplift

Make gather the web-data engine that offers the SUPERSET of the best features of
browser-use, Scrapling, crawlee, and firecrawl, is more performant than each on
its own ground, AND is the only one whose every operation carries a re-verifiable
receipt. Then wire those capabilities into learn, forum, and index.

Capability is the price of entry, not the differentiator. The receipt is a
MULTIPLIER on top of being the most capable and fastest choice; it is never a
substitute for a feature a user actually needs. If a competitor does something
users pick it for, gather must do that thing at least as well (zero-dep where it
can, via an optional capability backend where it must) and additionally witness
it. "Honest but less capable" is a losing position and is out of scope.

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

Wedges (done = best-in-class capability + tests + negative fixture + docs +
version bump + PR-ready; EVERY wedge ALSO emits its receipt):
  1. EXTRACT: HTML to Markdown/text/structured, CSS-lite selection, adaptive
     element relocation. Match firecrawl markdown + Scrapling selectors.
     [receipt: per-block path+hash, MATCH/RELOCATED/DRIFT/GONE]
  2. FETCH: conditional GET/ETag, retry/backoff, redirect provenance, HTTP
     concurrency, on-disk response cache (dev mode). Match Scrapling.Fetcher.
     [receipt: bytes + headers digest, redirect chain]
  3. CRAWL + MAP: concurrent resumable crawler, frontier BFS/DFS, sitemap +
     robots, URL canonicalization/dedup, depth/page limits, per-host throttle.
     Match crawlee queue + firecrawl crawl/map. [receipt: witnessed crawl ledger]
  4. STRUCTURED EXTRACT: schema to JSON via CSS/XPath/regex selectors with an
     adaptive-relocation fallback; every field bound to a source node + hash; a
     REJECT rule forbids any value not present in fetched content. Match firecrawl
     extract, beat it on precision. [receipt: field-to-node binding]
  5. CAPABILITY BACKENDS (the parity layer; all optional + capability-gated, with
     a stdlib fallback or an honest UNVERIFIABLE when absent, never a fake):
       a. BROWSER: JS render, click/fill/scroll, screenshot. Match browser-use +
          Scrapling Dynamic.
       b. STEALTH: TLS/browser impersonation transport, proxy rotation, session +
          fingerprint persistence, Cloudflare handling. Match Scrapling stealth +
          crawlee sessions.
       c. FAST PARSE: optional lxml/selectolax backend to win raw parse speed;
          stdlib stays the default and the fallback.
     [receipt: which backend + capability level produced each artifact]
  6. SEARCH + AGENT INTAKE: web-search-to-content and a URL-less gather agent
     loop. Match firecrawl search + agent. [receipt: query + source set]
  7. DX + PERFORMANCE: interactive CLI shell, dev-mode cache, pause/resume
     everywhere, JSON/JSONL exports, and MCP tools for all of the above; publish
     an honest benchmark table (fast backend on and off) against the competitors'
     numbers. Win on speed with the fast backend; state the zero-dep number too.
  8. INTEROP: gather crawl/corpus to index context-envelope + graph feed; gather
     extraction to a forum evidence lane; gather selector-provenance to a learn
     proof-lesson. Each interop carries the best capability of that flagship's
     category, not only the receipt. Proven end-to-end on the organ-bundle spine.

Organically complete when the capability superset above is shipped and green (a
user can pick gather over any single competitor on features AND speed AND
verifiability), the three interop demos pass end-to-end, docs + version bumped,
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
- Wedge 3: DONE on the same branch.
  - `src/gather/crawl.py` — a competitive crawler (concurrent wave fetching,
    BFS/DFS frontier, URL canonicalization + dedup, robots.txt via stdlib
    `robotparser`, sitemap discovery, depth/page caps, per-host throttle, and
    pause/resume via a serializable `CrawlState`) PLUS an append-only,
    hash-chained `CrawlLedger` a reviewer can re-derive to prove the crawl was
    not reordered, truncated, or edited.
  - Tests: `tests/test_crawl.py` (11; full suite 323 passed), including dedup,
    depth/page caps, robots block, sitemap seeding, resume-across-pause chain
    continuity, concurrent-workers parity, and ledger tamper detection.
- Wedge 4: DONE on the same branch.
  - `src/gather/schema_extract.py` — `extract_schema` (schema of CSS-lite
    selectors + optional attr/regex/many to a JSON record, each field bound to a
    source node path + hash; the firecrawl `extract` shape) AND `verify_record`,
    the hallucination-REJECT: any value in a proposed record not grounded in the
    fetched content is rejected. Turns LLM extraction from trust-the-model into
    prove-it-against-the-source.
  - Tests: `tests/test_schema_extract.py` (6; full suite 329 passed), including
    tamper detection and a hallucinated-field rejection negative.
- Wedge 5 (capability backends: browser / stealth / fast-parse): in progress.
- Wedges 6 through 8: not started.
