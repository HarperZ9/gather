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
information that is not sitting in one place but has to be synthesized from fragments.

The accountability that makes that safe is one rule: the receipt records how each item was
obtained. A transcript read from captions, a page read through a browser, text recognized
from a scan, speech transcribed from audio, and a fact synthesized from fragments are all
valid items, but they are not equally direct. The `method` on every item keeps that on the
record (`yt-dlp`, `browser-extract`, `ocr`, `transcribe`, `synthesized`), so a quote is
never confused with an inference, and what was hard to get is never dressed up as if it
were lying in the open.

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

The `parse` command consolidates already-harvested files (a yt-dlp `info.json` and its
`.vtt` captions) into items, scope-filters them, and emits the witnessed digest, all
offline:

```bash
python examples/demo.py        # no install, nothing to download
```

```
gathered 3 item(s)
by kind: {'comment': 1, 'metadata': 1, 'transcript': 1}
digest seal: 9f2c...           | verified: True
```

Live intake of a video needs the `yt-dlp` tool on PATH (the external tool the video
adapter shells out to; not a Python dependency):

```bash
gather video "https://youtu.be/<id>" --comments --scope "rubik,group theory"
gather parse harvested/<id>.info.json --vtt harvested/<id>.en.vtt
```

## What's here

- `gather.item`: an `Item` and its `Provenance` receipt; `make_item` computes the receipt from the content.
- `gather.source`: the `Source` adapter shape (the isolated impure edge) and a `Catalog` of what was gathered.
- `gather.scope`: the scope-to-telos filter, deterministic and order-preserving.
- `gather.digest`: the witnessed, provenance-stamped digest with a re-checkable seal.
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
