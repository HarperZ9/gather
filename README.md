<p align="center"><img src=".github/assets/banner.svg" alt="gather: Research intake that reaches the hard places: gated APIs, paywalls, JS-walled pages, scanned PDFs." width="100%"></p>

**Research intake that reaches the hard places: gated APIs, paywalls, JS-walled pages, scanned PDFs.**

[![PyPI](https://img.shields.io/pypi/v/gather-engine?style=flat-square&labelColor=14041b&color=f8cc43)](https://pypi.org/project/gather-engine/)
[![license](https://img.shields.io/badge/license-Gather_Fair--Source-8f8095?style=flat-square&labelColor=14041b)](LICENSE)
[![CI](https://github.com/HarperZ9/gather/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/gather/actions/workflows/ci.yml)
[![downloads](https://img.shields.io/pypi/dm/gather-engine?label=downloads&style=flat-square&labelColor=14041b)](https://pypi.org/project/gather-engine/)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&labelColor=14041b)
![deps: none (core)](https://img.shields.io/badge/core%20deps-none-success?style=flat-square&labelColor=14041b)

gather pulls research out of the places most tools break on: arXiv papers, authenticated JSON APIs, JavaScript-rendered pages via a real headless browser, scanned images through OCR, and audio through transcription, alongside video, web, feeds, and local docs. The core runs with zero third-party runtime dependencies, and the same engine is reachable from the CLI, MCP tools, and plain Python. Every run writes a receipt you can re-check.

[Project Telos](https://harperz9.github.io) | [gather](https://github.com/HarperZ9/gather) | [crucible](https://github.com/HarperZ9/crucible) | [index](https://github.com/HarperZ9/index) | [forum](https://github.com/HarperZ9/forum) | [telos](https://github.com/HarperZ9/telos) | [learn](https://github.com/HarperZ9/learn) | [emet](https://github.com/HarperZ9/emet) | [buildlang](https://github.com/HarperZ9/buildlang)

## Features

- **Extract any page to LLM-ready Markdown.** `gather extract` turns a URL or local HTML file into structured Markdown plus a per-block record binding every block to its source node path and content hash. `gather markdown` prints the Markdown alone.
- **Crawl whole sites.** A concurrent, resumable crawler with robots.txt, sitemap discovery, URL dedup, and per-host throttling. `gather crawl <url> --depth 2 --max-pages 50` emits an append-only, hash-chained ledger of the crawl as JSON.
- **Track elements across redesigns.** Fingerprint a scraped element once, then relocate it in any later version of the page and get a typed MATCH, RELOCATED, DRIFT, or GONE verdict (`gather.track`, Python API).
- **Structured extraction with a hallucination check.** `gather.schema_extract` binds schema fields to source nodes, and `verify_record` rejects any LLM-proposed field value not grounded in the fetched content.
- **Streaming extraction.** `gather.stream` parses an HTML stream chunk by chunk and emits partial-update commits as blocks complete, each folded into a hash chain, so a streamed extraction is replayable.
- **Hard-source adapters behind one shape.** Video with captions and comments (`yt-dlp`), static web, RSS/Atom feeds, local docs, arXiv, PDFs (`pdftotext`), authenticated JSON APIs (token from env, never logged), JS-rendered pages (headless Chromium), scanned images (`tesseract`), and audio (`whisper`). Each external tool is optional and only needed for its own adapter.
- **Scholarly-graph federation.** `gather scholar` queries OpenAlex, Semantic Scholar, and Crossref in one call, dedupes results by normalized DOI (never a fuzzy title match), and can capture citation edges as first-class records with `--edges`.
- **A durable local corpus.** Any fetch command takes `--store DIR`: bodies are content-addressed and deduped by hash, and `gather corpus list|verify|digest|runs|search|stats|prune|availability` inspects, re-checks, and queries what you stored.
- **Multi-source runs.** `gather run config.json` orchestrates many sources, a scope filter, and optional synthesis into one recorded session kept in the corpus history.
- **Three surfaces, one engine.** The full CLI, an MCP stdio server (`gather mcp`, tools `gather.status`, `gather.doctor`, `gather.docs`, `gather.arxiv`, `gather.federation`, `gather.run`), and a plain Python API.
- **Zero-dependency core, opt-in speed.** The core is pure standard library. `gather-engine[fast]` adds lxml parsing (about 2x on large documents), `[browser]` adds Playwright JS rendering, `[stealth]` adds curl_cffi TLS impersonation. `gather caps` reports what your install can actually do; a missing capability is reported as such, never faked.

## Install

```bash
pip install gather-engine
```

The distribution is `gather-engine`; it installs the `gather` command and the `gather` package (`import gather`). Python 3.11+. From a source checkout, `python -m gather` runs the same CLI.

## Quickstart

Extract a page to Markdown with a per-block receipt:

```bash
gather extract https://example.com/article
```

```json
{
  "blocks": [
    {"path": "html[1]/body[1]/h1[1]", "sha256": "7e8cd2056da7...", "tag": "h1"},
    {"path": "html[1]/body[1]/p[1]",  "sha256": "64ec88ca00b2...", "tag": "p"}
  ],
  "content_sha256": "ef4430f5f70f...",
  "markdown_sha256": "752cce8836dd...",
  "method": "html-extract",
  "url": "https://example.com/article"
}
```

Then try the rest of the surface:

```bash
gather caps                                    # what this install can do (fast / browser / stealth)
gather crawl https://example.com --depth 2     # a hash-chained crawl ledger as JSON
gather arxiv "aperiodic monotile" --store ./corpus
gather scholar "10.1234/monotile" --edges --json
gather docs ./research-notes --scope "rubik,group theory"
gather corpus verify ./corpus                  # re-hash every stored body; non-zero exit on corruption
```

Offline demo, no install of extra tools, nothing downloaded:

```bash
python examples/demo.py        # one video parsed, scoped, digested, then a tampered receipt caught
python examples/pipeline.py    # the whole pipeline: run -> store -> verify -> recall, offline
```

`demo.py` prints each item with its hash and `verify=True`, then flips one receipt and shows the digest verification fail. The hash prefixes vary; the verify results are pinned by the test suite. For a browser-viewable version of the same proof, open [examples/gather-demo.html](examples/gather-demo.html).

## Worked example: a mixed-source corpus

Gather from three different source types into one corpus, then re-check it:

```bash
gather web  "https://example.com/article" --store ./corpus
gather arxiv "2301.12345" --store ./corpus
gather docs ./notes --scope "monotile,tiling" --store ./corpus
gather corpus list ./corpus                 # every item with source, method, and hash
gather corpus search ./corpus --terms tiling --method http-get --json
gather corpus verify ./corpus               # MATCH per body, non-zero exit if anything is corrupt
gather corpus availability ./corpus         # per-record availability with typed outcomes
```

Every item carries its source, ref, method, timestamp, and a sha256 of the content, so `verify` can prove later that nothing in the corpus was altered, and `search` filters by scope terms, source, kind, or method.

## Source federation, offline

Plan a fleet of sources before probing any of them:

```bash
gather federation validate registry.json --json   # check rows against a closed contract
gather federation plan registry.json --json       # one deterministic capture plan per source
gather federation policy policy.json --json       # audit retry/backoff rules as typed verdicts
gather federation entity entities.json --json     # audit entity-resolution matches
```

All four run offline; no probe fires. A registry row is a catalog fact and is never reported as coverage, availability, or content.

## Optional capability backends

```bash
pip install 'gather-engine[fast]'      # lxml, about 2x parse speed on large docs
pip install 'gather-engine[browser]'   # Playwright JS render (then: playwright install chromium)
pip install 'gather-engine[stealth]'   # curl_cffi TLS/browser impersonation
```

The core never grows a hard dependency. Install a backend and it registers; skip it and the stdlib path or an explicit UNVERIFIABLE result stands in.

## Python API

```python
from gather.web import WebSource
from gather.digest import digest, verify_digest

items = WebSource().fetch("https://example.com/article")
d = digest(items)          # a sealed digest over every item's receipt
assert verify_digest(d)    # re-derive the seal; False if anything was altered
```

The same seams the CLI uses are importable: `gather.extract`, `gather.crawl`, `gather.track`, `gather.schema_extract`, `gather.stream`, `gather.search`, `gather.store`, `gather.run`, and the source adapters. [ARCHITECTURE.md](ARCHITECTURE.md) maps the modules and seams.

## Security notes

The `web` adapter reads static HTML and does not run JavaScript; a client-rendered page yields its shell, and the method says so. The `browser` adapter runs a real headless browser and is the most exposed edge: its host guard covers only the first navigation, so do not point it at untrusted URLs where internal services are reachable. The threat model is in [ARCHITECTURE.md](ARCHITECTURE.md). Credentials enter only through `gather.credentials`, read from the environment by name, never logged, never written into a receipt or URL.

## Documentation

- [docs/INTRODUCTION.md](docs/INTRODUCTION.md): what gather is, core concepts, and a first-ten-minutes walkthrough.
- [USAGE.md](USAGE.md): the operator surface, command by command.
- [ARCHITECTURE.md](ARCHITECTURE.md): the design map, seams, and threat model.
- [docs/WEB-ENGINE-UPLIFT.md](docs/WEB-ENGINE-UPLIFT.md): the web-data engine roadmap and benchmarks.
- [docs/ENTERPRISE-READINESS.md](docs/ENTERPRISE-READINESS.md): context envelopes, action receipts, and host-neutral operation for unattended agents.
- [CHANGELOG.md](CHANGELOG.md): version history. Current release: 1.6.1.

Peer projects: [crucible](https://github.com/HarperZ9/crucible) (judgment), [index](https://github.com/HarperZ9/index) (code maps), [forum](https://github.com/HarperZ9/forum) (orchestration), [telos](https://github.com/HarperZ9/telos) (the engine).

## Why it matters

Research breaks when sources become a blur. One rule sits underneath all of it: every item records how it was obtained. A quote fetched over HTTP, a page rendered in a browser, text recognized from a scan, and a statement synthesized from fragments are all valid items, but they are not equally direct, and the `method` field plus the digest seal keep that difference on the record and re-checkable. If that discipline matters to your workflow, gather was built for it; if you just need the intake, it never gets in your way.

## License

Gather is fair-source: open to read, run, and build on, with commercial use reserved so the project can fund its own development. See [LICENSE](LICENSE).

## Work with it

Bring papers, transcripts, local docs, or awkward public materials that need provenance before synthesis; source-adapter testing and research-lab feedback are the most useful pressure right now. To develop against a checkout:

```bash
python -m pip install -e ".[dev]"
python -m pytest        # 417 tests
python -m ruff check src tests examples
python -m mypy
```

Keep the README, package metadata, and examples aligned with current behavior before opening a PR.

## What this believes

This tool is one lane of a family that holds a single belief steady across
every surface: knowledge open to anyone who can attain the means; acceptance
decided by external checks, never reputation; every result re-runnable;
honest nulls first-class; ownership earned by comprehension; learning woven
into the work. The full text lives in [CREDO.md](CREDO.md).
