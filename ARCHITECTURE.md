# Gather: architecture

Gather is the afferent organ of the constellation: it brings information in from scattered,
often awkward sources, and records how each piece was obtained so that downstream a quote is
never confused with an inference. This document is the map of how it is built and why.

## The one shape: `Source`

Every kind of intake is an adapter behind a single shape (`gather.source.Source`):

```python
class Source(Protocol):
    name: str
    def fetch(self, target: str) -> list[Item]: ...
```

One string in, a list of receipted `Item`s out. An adapter may use the network, a third-party
tool, or a credential; it hides all of that behind this shape. The rest of Gather imports none
of it. Awkward access is an adapter problem, not a system problem. Shipped adapters: `video`
(yt-dlp), `web` (static http), `feed` (RSS/Atom), `docs` (local files), `arxiv` (the arXiv API),
`pdf` (pdftotext), and `api` (authenticated JSON).

## The receipt: `Item` and `Provenance`

Every `Item` carries a `Provenance` receipt (`gather.item`):

- `source`, `ref` (the source-scoped reference), `method` (HOW it was obtained), `fetched_at`,
- `sha256` of the item's own text, and `derived_from` (the content hashes of an inference's inputs).

`make_item` computes the hash and **enforces the method ladder** (below). `item.verify()`
re-hashes the text and confirms it still matches the receipt. The hash always fingerprints the
item's own text: for a fetched item that text is the source content, for a derived item it is the
inference, so the hash witnesses what the item actually is.

## The method ladder (`gather.method`)

A method is `direct` (a fetch/read/transcription) or `derived` (`compiled`/`synthesized`), or
`unknown` (an unregistered label, which makes no claim). `make_item` enforces consistency: a
direct item cannot carry `derived_from`, and a derived item cannot lack it. So a fetch cannot be
dressed up as an inference, nor an inference as a quote. The honesty is mechanical, not a promise.

## Derivation: the `Synthesizer` seam (`gather.derive`)

A derived item is assembled or inferred from other items. `derive()` is the low-level builder; it
defaults to `method="compiled"` and **refuses** `method="synthesized"`. A `synthesized` item is
reachable only through `synthesize_item(synth, ...)`, where a real model stands behind the
`Synthesizer` seam. The default `NullSynthesizer` performs a deterministic, extractive compilation
(`method="compiled"`) and invents nothing. Gather never labels something a synthesis unless a model
actually performed one.

## The witness: `digest` (`gather.digest`)

A run folds its items' receipts into a `Digest` with a re-checkable `seal`. The seal is order
independent across items (the receipts are sorted) but covers every field of each receipt
(content hash, kind, id, title, source, ref, method, and `derived_from` in order), so relabelling
how an item was obtained, retitling it, or rewriting an inference's inputs all break the seal
exactly as tampering with the content does. `digest_of_receipts` folds a seal from stored catalog
rows without re-reading bodies.

## The network edge (`gather.net`)

HTTP lives in exactly one place: `http_get`. It allows only http/https, blocks private,
loopback, link-local, and reserved hosts on the initial URL **and on every redirect hop** (so the
guard cannot be slipped by a redirect inward, the cloud-metadata SSRF), caps the body, and warns
on truncation. Optional headers (e.g. an Authorization header) are sent but never logged. The pure
`decode_body` and the host check are tested directly; the live request is the isolated edge.

## Credentials (`gather.credentials`)

Secrets enter in one place: `require_secret(name)` reads from the environment, never from source,
a config Gather reads, or a URL. The value is never logged and never appears in an error (the
message names only the missing variable), never stored in an Item or receipt. The `api` adapter is
the worked example: the token is read from the environment and sent in a request header, so it
never reaches the URL, the receipt, or the disk.

## The corpus (`gather.store`)

A `Corpus` is durable, content-addressed storage. Bodies live at `objects/ab/cdef...` keyed by the
sha256 of their content, so identical content is stored once (the natural dedup), written
temp-then-rename and fsync'd (durable by default). `catalog.jsonl` is an append log of one row per
**distinct receipt**: dedup is at the body level only, so two different items with identical text
keep both receipts and share one body, and no provenance is dropped. `verify()` re-hashes every
stored body and reports MATCH / MISSING / CORRUPT, making the digest's proof durable over a growing
corpus. The catalog and run history stream a row at a time; a content hash is validated as 64 hex
before it is used to build a path, so a tampered catalog cannot traverse out of the store.

## The witnessed run (`gather.run`)

`gather_run` orchestrates one session: fetch each `(source, target)` job, collect, scope-filter,
optionally fold into one synthesized item through the Synthesizer seam, digest, and optionally
store. The clock is injected, so given the same fetched items the run is deterministic and
replayable. It returns a `RunRecord`: a witnessed record (when, targets, scope, counts, the items'
digest seal) with its own seal over those fields, re-checkable from disk via `RunRecord.from_dict`
and `corpus runs --verify`. The scope filter and the synthesizer are composition seams that default
to Null, so the run stands alone and a model-based scope or synthesizer plugs in without the run
importing it.

## Recall (`gather.recall`)

`recall` queries a stored corpus by substring scope terms and exact `source`/`kind`/`method`
filters (OR within a filter, AND across). Cheap metadata filters are answered from the row before
any body is read; only survivors are loaded and **re-verified**, so a missing or corrupt body is
skipped and reported (`recall_audited`), never returned as if intact. Downstream organs draw
scoped, trustworthy subsets through this.

## Determinism and the zero-dependency core

Clocks are injected everywhere time is recorded; there is no wall-clock or randomness in the
deterministic paths, so replay and verification are trustworthy. The core is pure standard library.
An adapter may pull in whatever its source demands, but only behind the `Source` shape, and only at
the impure edge.

## Peer composition

Gather composes with the rest of the constellation through clean protocol seams, it does not
absorb or get absorbed. The digest is the contract downstream organs (index, refine, the crucible)
consume. The scope, synthesizer, and store are seams that default to a Null so Gather stands alone.
This is why Gather is deliberately impure and is **not** part of index, which is zero-dependency,
offline, and deterministic and would forfeit exactly that if it grew a scraper.
