# Readable corpus context selection contract

## User workflow

A human or agent can inspect a stored Gather corpus, see bounded source/comment excerpts with integrity status, select explicit row/range windows, and export a portable private context payload for a downstream Journey or agent.

## Non-goals

- No network access is added.
- No semantic truth or claim-support verdict is produced.
- No whole-corpus export is the default.
- No arbitrary object path or caller-provided body path is accepted.

## Python API

`gather.context.inspect_corpus(corpus, *, max_rows=20, excerpt_chars=600, max_catalog_bytes=5000000, max_catalog_rows=10000, max_body_bytes=5000000, max_read_bytes=10000000)` returns:

- `schema: gather.readable-corpus/v1`
- `corpus_digest`: current digest seal computed from catalog rows
- `rows`: catalog-order row descriptors with `row_ref`, source/ref/method/hash identity, `body_status`, `availability`, bounded `excerpt`, and `omissions`

`gather.context.select_context(corpus, selections, *, expected_corpus_digest, max_rows=12, max_total_chars=12000, default_limit=1200, max_catalog_bytes=5000000, max_catalog_rows=10000, max_body_bytes=5000000, max_read_bytes=10000000)` returns:

- `schema: gather.readable-context/v1`
- `corpus_digest`: current digest seal
- `selections`: selected text windows with row identity, full body hash, range, selected text, and omissions
- `selection_digest`: deterministic hash over corpus digest, selected text, source refs, full body hashes, ranges, and omissions
- `does_not_prove`: includes truth/support/completeness boundaries

The Python API also accepts a same-process `CorpusRootDescriptor` from callers
that already hold an opened corpus root fd/HANDLE and its expected
`CorpusRootIdentity`. Gather duplicates that borrowed authority, validates the
duplicate against the expected identity, and then uses the same confined reader
for catalog and body reads. The caller must keep the original descriptor live
through the call. Descriptor handoff is intentionally Python-only; CLI and MCP
continue to accept corpus directory strings, not raw handles or file
descriptors.

The selection call rejects stale `expected_corpus_digest` values, duplicate row refs, unexpected selection fields, unsafe corpus paths, over-budget text windows, and missing/corrupt/oversized selected bodies. Inspection surfaces those body failures with typed omissions and does not mark a row-limited partial inspection as a fully verified corpus.

Text and range semantics are intentionally text-level. Stored bodies are first verified against the exact source text receipt. New rows carry a versioned exact-UTF8 storage witness, folded into the corpus digest, so consumers that pin `expected_corpus_digest` can detect witness stripping or codec changes. Legacy rows without that witness are reconstructed only when exact UTF-8 bytes or the inverse of the old Windows text writer's LF-to-CRLF expansion yields exactly one source text matching the receipt. That reconstructs source text; it does not prove historical raw object-byte integrity.

Readable excerpts and selected `text` are a view: CRLF or CR line endings are normalized to LF after source verification. `start` and `limit` are Python string character offsets over that readable view. `sha256`, `verified_sha256`, and `source_sha256` bind the exact source text. `view_sha256` binds the full LF-normalized readable view, and `view_codec` names the transformation. A selected slice does not need to hash to either full-body value. The selected slice, range, source refs, source/view hashes, storage status, and omissions are separately bound into `selection_digest`.

The corpus digest is the pinned trust boundary for selection. A caller that obtained a storage-witnessed digest from inspection or `Corpus.digest()` should pass that value back through `expected_corpus_digest` / `--expect-digest`; selection fails if the catalog later strips or changes a sealed storage witness. Recomputing the digest after local catalog mutation accepts the current catalog state and is not an external anti-downgrade proof.

The confined reader pins the corpus root it opens or the same-process descriptor
it duplicates, and uses that authority for catalog and selected-body reads. On
Linux/WSL filesystems where retained directory fds cannot supply stable
confined child opens, currently including WSL Windows-drive 9p/v9fs mounts,
Gather refuses each opened corpus, descendant directory, or catalog/body
file descriptor before reading corpus metadata or bodies. Linux classification
uses the opened fd's mount ID from `/proc/self/fdinfo` and the matching entry in
`/proc/self/mountinfo`; unavailable mount information also refuses the read.
This avoids assumptions about native `statfs` structure layouts. Outside Linux this
fd mount-type denylist is unavailable; Gather still enforces its existing
openat, no-follow, and type checks and does not claim unsupported-mount
detection there. It does not accept
caller-provided object paths, and it does not prove that a higher-level host
resolved the corpus path under an approved workspace parent without a race.
Hosts that derive a corpus path from a workspace grant must enforce that
workspace-parent relationship at their own boundary.

## CLI/MCP parity

CLI:

- `gather corpus context DIR --json [--max-rows N] [--excerpt-chars N] [--max-catalog-bytes N] [--max-catalog-rows N] [--max-body-bytes N] [--max-read-bytes N]`
- `gather corpus context DIR --json --select ROW_REF[:START[:LIMIT]] --expect-digest SHA256 [--max-total-chars N] [--max-catalog-bytes N] [--max-catalog-rows N] [--max-body-bytes N] [--max-read-bytes N]`

MCP:

- `gather.context` with `corpus`, optional `select`, required `expected_corpus_digest` for selection, and the same caps.

## Payload boundary

The payload is private context and may include selected bounded source text plus source/ref metadata exactly enough to preserve provenance. Context selection does not read native credential stores or intentionally add Gather credential environment values, but selected source text or URLs can contain sensitive material if the corpus contains it. It does not perform arbitrary secret detection, semantic truth checking, or claim-support validation. Claim validation remains a separate Journey/Crucible step, and publishing remains a downstream policy decision.
