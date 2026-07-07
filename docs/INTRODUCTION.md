# Introduction to gather

gather is a research-intake engine. It pulls content out of sources that most
tools break on, gated APIs, JavaScript-walled pages, scanned PDFs, audio, paywalled
scholarly graphs, and it turns whole websites into LLM-ready Markdown, crawl
ledgers, and structured records. One engine, three surfaces: a full CLI, an MCP
stdio server, and a plain Python API. The core has zero third-party runtime
dependencies; everything heavier is an opt-in edge.

Install:

```bash
pip install gather-engine
```

That gives you the `gather` command and the `gather` Python package. Python 3.11+.

## Why it exists

Intake is where research quietly goes wrong: a quote gets mixed up with a
summary, a scraped page changes under you, a model fills a field the page never
said. gather's answer is a receipt on every operation, the source, the method,
and a content hash, sealed so it can be re-checked later. You do not have to
care about that to use the tool; it is simply always there when you need to
prove where something came from.

## Core concepts

- **Item.** The unit of intake. Every item carries its text plus a provenance
  record: source, ref, method, fetch time, and a sha256 of the content.
- **Method.** How the content was obtained: `http-get` for a static page,
  `browser-extract` when JavaScript ran, `ocr` for a scan, `transcribe` for
  audio, `compiled` or `synthesized` for derived text. A quote and an inference
  are never confused.
- **Source adapter.** Each source is a small adapter behind one shape:
  `fetch(target) -> list[Item]`. Network access, external tools, and
  credentials live inside adapters and nowhere else.
- **Digest.** A run folds its items' receipts into one sealed digest.
  Re-derive the seal and you can confirm nothing was altered.
- **Corpus.** A durable, content-addressed store (`--store DIR`). Bodies are
  deduped by hash; `gather corpus verify` re-hashes everything against its
  receipts.
- **Capabilities.** Optional backends (`fast`, `browser`, `stealth`) register
  when installed. `gather caps` reports what your install can do; a missing
  capability is reported honestly, never faked.

## Your first ten minutes

Everything below was run against gather 1.6.0.

**1. Check the install.**

```bash
gather --version        # gather 1.6.0
gather caps             # which web-engine backends this install can use
```

**2. Extract a page to Markdown.** This is the fastest way to see the engine
work. It accepts a URL or a local `.html` file:

```bash
gather markdown https://example.com     # structured Markdown to stdout
gather extract https://example.com      # Markdown receipt: per-block source path + hash, as JSON
```

`extract` returns a JSON record where every Markdown block is bound to the DOM
node it came from (`html[1]/body[1]/p[1]`) and a sha256 of that block's content.

**3. Run the offline demo.** No network, no external tools:

```bash
python examples/demo.py
```

It parses a saved video harvest into items with receipts, scopes them, seals a
digest, then tampers with one receipt and shows verification fail. The last line
is the point: `after tampering one receipt, digest verifies: False`.

**4. Build a small corpus.** Point a few adapters at real sources and store the
results in one place:

```bash
gather arxiv "aperiodic monotile" --store ./corpus
gather web "https://example.com/article" --store ./corpus
gather docs ./my-notes --store ./corpus
```

**5. Inspect and re-check it.**

```bash
gather corpus list ./corpus                     # every item: source, method, hash
gather corpus search ./corpus --terms monotile  # substring search over title + body
gather corpus verify ./corpus                   # re-hash every body; non-zero exit on corruption
```

**6. Crawl something.**

```bash
gather crawl https://example.com --depth 2 --max-pages 20
```

The output is an append-only, hash-chained ledger of the crawl: robots.txt is
honored, sitemaps are used for discovery, and each page entry chains to the
previous one, so the ledger can be re-derived and checked for edits.

That is the core loop: fetch, store, inspect, re-check. The harder adapters
(`pdf`, `browser`, `ocr`, `transcribe`, `video`) work the same way and each
needs only its own external tool on PATH (`pdftotext`, `chromium`, `tesseract`,
`whisper`, `yt-dlp`).

## The web-data engine

Version 1.6.0 added a full web toolkit on top of the adapters:

- `gather extract` and `gather markdown`: HTML to Markdown with per-block
  provenance (CLI and `gather.extract` in Python).
- `gather crawl`: the concurrent, resumable crawler with the hash-chained
  ledger.
- `gather.track` (Python): fingerprint an element once, relocate it in a
  redesigned page, and get a typed MATCH, RELOCATED, DRIFT, or GONE verdict.
- `gather.schema_extract` (Python): bind schema fields to source nodes;
  `verify_record` rejects any LLM-proposed value not grounded in the fetched
  content.
- `gather.stream` (Python): streaming extraction that emits hash-chained
  partial-update commits as blocks complete in an HTML stream.
- `gather.search` (Python): a pluggable search-provider seam that turns a query
  into fetchable leads.

The roadmap and benchmark notes are in [WEB-ENGINE-UPLIFT.md](WEB-ENGINE-UPLIFT.md).

## Scholarly sources

`gather scholar` federates OpenAlex, Semantic Scholar, and Crossref in one
query. Records are deduped by normalized DOI (a DOI is the only join key, never
a fuzzy title match), every provider's contribution is kept, and `--edges`
captures citation links as first-class records sealed alongside the papers:

```bash
gather scholar "10.1234/monotile" --edges --json
gather arxiv 2301.12345 --json
```

## MCP and automation

`gather mcp` serves the engine over MCP stdio with six tools: `gather.status`,
`gather.doctor`, `gather.docs`, `gather.arxiv`, `gather.federation`, and
`gather.run`. `gather.run` accepts an inline config object or a config path, so
an agent host does not need to stage files. `gather status --json` and
`gather doctor --json` emit machine-readable envelopes for health checks.
[ENTERPRISE-READINESS.md](ENTERPRISE-READINESS.md) covers unattended operation.

## Where to go next

- [../USAGE.md](../USAGE.md): the operator surface, command by command.
- [../ARCHITECTURE.md](../ARCHITECTURE.md): the design map, module seams, and
  the threat model (read this before pointing the browser adapter at untrusted
  URLs).
- [WEB-ENGINE-UPLIFT.md](WEB-ENGINE-UPLIFT.md): where the web engine is headed.
- [../CHANGELOG.md](../CHANGELOG.md): version history.
- Peer projects: [crucible](https://github.com/HarperZ9/crucible),
  [index](https://github.com/HarperZ9/index),
  [forum](https://github.com/HarperZ9/forum),
  [telos](https://github.com/HarperZ9/telos).
