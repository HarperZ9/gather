# Gather

![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![deps: none (core)](https://img.shields.io/badge/core%20deps-none-success.svg)
![license: fair-source](https://img.shields.io/badge/license-fair--source-blue.svg)

Research lives behind awkward access. Captions and comments on a video, papers behind an
arXiv gate, a library buried in a repo, an API with a credential wall, a fact that exists
only across scattered fragments and has to be put together. Most tools handle one of those
and break on the rest, and when they do reach something, you cannot tell later whether a
line was pulled straight from the source or pieced together along the way.

Gather is the research-intake organ that handles all of it cohesively, and records how.
It is the one place in the constellation where network access, third-party tools, and
credentials are allowed to live, isolated behind source adapters, so the rest stays clean.
Every item it brings back carries a provenance receipt, and a run emits a witnessed digest
that index, refine, and the crucible consume.

## Reach anywhere, and say how

The aim is to pull information from anywhere, including the extremely difficult: gated APIs,
auth and paywalls, JavaScript-walled pages, scanned PDFs, audio, obscure formats, and
information that is not sitting in one place but has to be synthesized from fragments. One
adapter ships today (video, below); the rest is the design the adapter seam is built for,
on the roadmap. What ships first is the accountability that has to be right before any of
the harder sources are safe to trust.

That accountability is one rule: the receipt records how each item was obtained. A
transcript read from captions, a page read through a browser, text recognized from a scan,
speech transcribed from audio, and a fact synthesized from fragments are all valid items,
but they are not equally direct. The `method` on every item keeps that on the record
(`yt-dlp`, `browser-extract`, `ocr`, `transcribe`, `synthesized`), so a quote is never
confused with an inference, and what was hard to get is never dressed up as if it were
lying in the open.

A derived item (one assembled or inferred from other items, rather than fetched) is the
sharp case, and the receipt is built for it. Its sha256 fingerprints the inference itself,
not its sources, because it is a new statement and can only witness itself; a `derived_from`
field records the content hash of each input, a re-checkable pointer back to the exact
source content. The digest seal folds in `method` and `derived_from` alongside the hash, so
relabelling an inference as a direct fetch, or quietly rewriting what it was built from,
breaks the seal exactly as altering the content does.

The honesty is mechanical, not a promise. The `method="synthesized"` label is reachable
only through the `Synthesizer` seam: the bare `gather.derive` builder defaults to `compiled`
and refuses to stamp `synthesized` at all, so an inferred claim can only come from a model
actually plugged into the seam (`synthesize_item` stamps the result with the synthesizer's
own method). With no model wired in, the default `NullSynthesizer` performs a deterministic,
extractive *compilation*: it assembles inputs verbatim, labels them `compiled`, and invents
nothing. So Gather never labels something a synthesis unless a model performed one.

## The discipline

- **One isolated impure edge.** Each source is a small adapter behind a single `Source`
  shape: `fetch(target) -> list[Item]`. The adapter can use the network, a tool, a
  credential, a browser, whatever the source demands; the rest of Gather imports none of
  that. Awkward access is an adapter problem, not a system problem.
- **A receipt on every item.** Each `Item` carries a `Provenance` (source, ref, method,
  time, and a sha256 of the content). Re-hash the content and you can confirm it is what
  was obtained, unaltered.
- **A witnessed digest out.** A run folds its items' receipts into one re-checkable seal.
  Downstream organs consume the digest; the seal lets a reader confirm it was not altered.
- **Scope to the work.** A deterministic scope filter keeps what serves the theses and
  drops the rest, and records how many it dropped.
- **A peer, not a feature.** Gather is deliberately impure, so it is not part of index
  (which is zero-dependency, offline, and deterministic, and would forfeit exactly that
  if it grew a scraper). It composes through the digest seam, the way Forum does.

## Watch it work

`examples/demo.py` parses an already-harvested video (a yt-dlp `info.json` plus its `.vtt`
captions) into items, each with a provenance receipt, scope-filters them, folds them into a
witnessed digest, then tampers with one receipt to show the seal catch it. All offline, no
install, nothing downloaded:

```bash
python examples/demo.py
```

```
parsed 3 items from one video, each with a receipt:
  metadata   abc123  sha256=40d9839ffb0e...  verify=True
  transcript abc123  sha256=f798cd2c334c...  verify=True
  comment    c1  sha256=301cf39d5091...  verify=True

scope to ['tile','monotile']: kept 3, dropped 0
witnessed digest: 3 receipts, seal 22b3603535ea..., verified True

after tampering one receipt, digest verifies: False  <- caught
```

The `gather` CLI does the same over real files, and `gather video` fetches a live one.
Live intake needs the `yt-dlp` tool on PATH (the external tool the video adapter shells
out to; not a Python dependency):

```bash
gather parse harvested/<id>.info.json --vtt harvested/<id>.en.vtt --scope "rubik,group theory"
gather video "https://youtu.be/<id>" --comments --scope "rubik,group theory"
```

## What's here

- `gather.item`: an `Item` and its `Provenance` receipt (with `derived_from` for inferences); `make_item` computes the receipt from the content.
- `gather.source`: the `Source` adapter shape (the isolated impure edge) and a `Catalog` of what was gathered.
- `gather.scope`: the scope-to-telos filter, deterministic and order-preserving.
- `gather.digest`: the witnessed, provenance-stamped digest with a re-checkable seal (folds in `method` and `derived_from`).
- `gather.derive`: the derive seam, building a derived item with `derived_from`; a `Synthesizer` seam whose `NullSynthesizer` default compiles verbatim (never fabricates a synthesis).
- `gather.video`: the first adapter, video intake via `yt-dlp`. Its parsing is pure and tested; the fetch is the impure shell.
- `gather.cli`: a `gather` command (`parse` offline, `video` live).

The core is pure standard library. A source adapter may pull in whatever its source
demands, isolated behind the `Source` shape.

## Roadmap

- **P1 (here).** One real, tested tool with a clean adapter interface: the video adapter, the provenance receipt, the scope filter, the witnessed digest, the catalog.
- **P2.** More adapters behind the same shape: arXiv and papers, code libraries, and the hard ones, gated APIs with isolated credentials, JavaScript-walled pages, PDFs and scans (OCR), audio (transcription), and synthesis adapters that derive a fact from fragments and record `method=synthesized` with what they derived it from.
- **P3.** Storage organization and management over the ingested corpus.
- **P4.** Scope-to-telos filtering deepened, and the witnessed digest composed with `provenance-sensorium` for a full origin receipt before any claim uses an item.

## License

Gather is fair-source: the code is open to read, run, and build on, with commercial use
reserved so the project can fund its own development. Copyright stays with the author. See
[LICENSE](LICENSE) for the exact terms.
