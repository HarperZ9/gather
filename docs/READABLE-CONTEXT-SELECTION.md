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

The selection call rejects stale `expected_corpus_digest` values, duplicate row refs, unexpected selection fields, unsafe corpus paths, over-budget text windows, and missing/corrupt/oversized selected bodies. Inspection surfaces those body failures with typed omissions and does not mark a row-limited partial inspection as a fully verified corpus.

Text and range semantics are intentionally text-level. Stored bodies are decoded as UTF-8, and CRLF or CR line endings are normalized to LF before content-hash verification and before applying ranges. `start` and `limit` are Python string character offsets over normalized text. `verified_sha256` and the full body hash are the `content_hash` of the whole normalized body text encoded as UTF-8; a selected slice does not need to hash to that full-body value. The selected slice, range, source refs, full body hash, and omissions are separately bound into `selection_digest`.

The confined reader pins the corpus root it opens and uses that authority for catalog and selected-body reads. It does not accept caller-provided object paths, and it does not prove that a higher-level host resolved the corpus path under an approved workspace parent without a race. Hosts that derive a corpus path from a workspace grant must enforce that workspace-parent relationship at their own boundary.

## CLI/MCP parity

CLI:

- `gather corpus context DIR --json [--max-rows N] [--excerpt-chars N] [--max-catalog-bytes N] [--max-catalog-rows N] [--max-body-bytes N] [--max-read-bytes N]`
- `gather corpus context DIR --json --select ROW_REF[:START[:LIMIT]] --expect-digest SHA256 [--max-total-chars N] [--max-catalog-bytes N] [--max-catalog-rows N] [--max-body-bytes N] [--max-read-bytes N]`

MCP:

- `gather.context` with `corpus`, optional `select`, required `expected_corpus_digest` for selection, and the same caps.

## Payload boundary

The payload is private context and may include selected bounded source text plus source/ref metadata exactly enough to preserve provenance. Context selection does not read native credential stores or intentionally add Gather credential environment values, but selected source text or URLs can contain sensitive material if the corpus contains it. It does not perform arbitrary secret detection, semantic truth checking, or claim-support validation. Claim validation remains a separate Journey/Crucible step, and publishing remains a downstream policy decision.
