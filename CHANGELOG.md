# Changelog

All notable changes to Gather. Versions follow semantic versioning; each minor release was
built behind a feature branch and reviewed before merge.

## 1.1.0

The hard sources, behind the same `Source` seam, each an isolated external-tool edge:

- `gather.browser`: JavaScript-rendered pages via a headless Chromium (`--dump-dom`), reusing the
  web text extractor. The receipt's `browser-extract` method records that JavaScript was run, so a
  rendered page is distinguished from a raw fetch; the same scheme + private-host SSRF guard applies.
- `gather.ocr`: text from a scanned image via `tesseract`. The `ocr` method records a machine
  reading of an image.
- `gather.transcribe`: a transcript from audio via a Whisper-style CLI. The `transcribe` method
  records a machine transcription.
- The scheme + private-host guard is now a shared `net.validate_public_http_url`, used by both the
  http and browser edges. External-tool paths are resolved to absolute paths so a filename starting
  with `-` cannot be read as a flag.

## 1.0.0

The first stable release. A whole-system review (correctness, security, and docs lenses) gated
the milestone; its findings are fixed here.

- Security: credentials (Authorization/Cookie) are stripped on a cross-origin redirect, so a
  compromised or open-redirecting endpoint cannot harvest a bearer token; routing headers
  (Host/Forwarded) that could desync the host guard are refused; the persisted run history is
  hardened against a malformed row.
- Integrity: the digest seal canonicalizes each receipt as a named-key object, so the
  receipt-to-bytes mapping is unambiguous by construction; a run dedups duplicate receipts before
  sealing, so a run's seal equals the corpus it stored; recall and verify now agree that a
  tampered (non-hex) sha is CORRUPT, not MISSING.
- Robustness: `gather run` rejects a non-list `scope`; feed entries with no derivable identity are
  skipped (matching arxiv).
- Public API: a curated top-level surface is re-exported from `gather` with `__all__`.
- Docs: the design map, threat model (including the DNS-rebinding residual), and limitations are
  stated where a user meets them; the security-contact and module list are corrected.

## 0.9.0

- Documentation and hardening for the 1.0 line: `ARCHITECTURE.md`, this changelog, and a full
  offline pipeline example.
- Split the CLI into an argument surface (`cli`) and command implementations (`commands`) so no
  module exceeds the size budget.

## 0.8.0

- `gather.credentials`: secrets enter in one place, read from the environment by name, never
  logged, never put in an Item, receipt, or URL; whitespace-only and newline-bearing values are
  rejected.
- `gather.api`: an authenticated JSON-API adapter, the worked example of the credentials pattern
  (token read from env, sent as a header, refused if it appears in the URL).
- `gather.method`: the method ladder. A method is direct or derived; `make_item` enforces that a
  direct item carries no derivation chain and a derived one does.
- `net.http_get` gained an optional headers parameter (sent, never logged).

## 0.7.0

- `gather.recall`: query a stored corpus by substring scope terms and source/kind/method filters
  (OR within a filter, AND across). Returned items are reconstructed and re-verified; missing or
  corrupt bodies are skipped and reported. New `corpus search` CLI action.

## 0.6.0

- `gather.run`: the witnessed gather session. Orchestrates fetch, scope, optional synthesis,
  digest, and store into one re-checkable `RunRecord` (re-checkable from disk). Scope and
  synthesizer are composition seams defaulting to Null. Durable run history in the corpus.

## 0.5.0

- `gather.store.Corpus`: durable, content-addressed storage. Bodies deduped by hash, every
  distinct receipt kept, `verify()` reports MATCH/MISSING/CORRUPT, fsync durability, path-traversal
  guarded. Every command gained `--store DIR`; new `corpus list/verify/digest` actions.

## 0.4.0

- `gather.arxiv`: papers from the arXiv API (a pure Atom parser), each Item carrying the abstract
  and metadata; the method records id-lookup vs search.
- `gather.pdf`: text from a local PDF via `pdftotext`, the isolated external-tool edge.

## 0.3.0

- Three adapters behind the same seam: `web` (static http + html.parser), `feed` (RSS/Atom), and
  `docs` (local files). `gather.net`: the single network primitive, with a scheme allowlist and a
  private-host SSRF block enforced on every redirect hop.

## 0.2.0

- Provenance hardening (de-laddered auto-captions, the seal folds in source/ref/method/derived_from,
  malformed-input guards) and `gather.derive`: the synthesis derive seam, where a `synthesized`
  label is reachable only through a model behind the `Synthesizer` seam and the default compiles.

## 0.1.0

- The foundation: the `Item` and its `Provenance` receipt, the `Source` adapter shape, the scope
  filter, the witnessed `Digest` with a re-checkable seal, the first adapter (`video` via yt-dlp),
  and the `gather` CLI.
