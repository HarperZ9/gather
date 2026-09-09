# Gather Usage

Gather turns difficult source intake into replayable, digest-backed research
packets. It is designed for local CLI use, MCP hosts, and larger Project Telos
workflows that need provenance before synthesis.

## Install

```bash
python -m pip install gather-engine
```

From a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
gather status --json
gather doctor --json
gather demo --json
gather --help
```

The same package can be exercised from source with:

```bash
python -m gather --help
```

## Pilot

```bash
gather pilot run MANIFEST --output DIR          # capture once, write report + receipt
gather pilot refresh DIR                        # re-capture monitored sources, archive the prior view
gather pilot verify DIR                         # network-free verification of the whole root
gather pilot bundle DIR --output FILE --visibility shared
gather pilot bundle DIR --output FILE --visibility full --include-private-evidence
```

Exit codes: manifest refusal exits `2`; a required-source failure or
verification failure exits `1`; success exits `0`. A full bundle (which carries
the private artifact root) requires `--include-private-evidence`. See
[docs/PILOT.md](docs/PILOT.md) for the manifest boundary and the
private/shared evidence split.


## Web-data engine

Each command prints a receipt as JSON.

```bash
gather caps                      # what this install can do (fast / browser / stealth)
gather extract <url|file.html>   # Markdown + a per-block provenance receipt
gather markdown <url|file.html>  # structured Markdown only
gather crawl <url> --depth 2 --max-pages 50   # a witnessed, hash-chained crawl ledger
```

Optional capability backends (core stays zero-dependency; a missing one degrades to
UNVERIFIABLE, never a fake):

```bash
pip install 'gather-engine[fast]'      # lxml, about 2x parse speed
pip install 'gather-engine[browser]'   # Playwright JS render (then: playwright install chromium)
pip install 'gather-engine[stealth]'   # curl_cffi TLS/browser impersonation
```

## Federation

Validate a source-federation registry and compile its capture plans, all offline:

```bash
gather federation validate registry.json --json
gather federation plan registry.json --json
```

A registry file is a list of source rows or `{"sources": [...]}`; each row carries
`id`, `system`, `family`, `domain`, `access`, `adapter`, `url`, `scope`, and
`priority`. Validation is a closed contract: unknown access tokens, priorities, or
extra fields are typed rejections, and the validated snapshot is sealed, so a row
cannot be edited after witnessing without breaking the seal. `plan` adds one
deterministic capture plan per source, derived from its access policy. Neither
command probes a source, and a registry row is never reported as coverage or
availability.

Two further audits treat a federation decision as a sealed claim surface:

```bash
gather federation policy policy.json --json
gather federation entity entities.json --json
```

A policy file is a list of rules or `{"rules": [...]}`; each rule carries `rule`,
`source_capture_ref` (a content-hash capture ref), `failure_class`, and `superseded`.
Each failure class maps to one typed verdict (429 to `retryable_source_lead`, 403 to
`access_escalation`, 503 to `retry_after`). A rule with no provenance capture, an
unknown failure class, or a superseded flag is a typed rejection.

An entity file is a list of candidates or `{"candidates": [...]}`; each candidate
carries `candidate_id`, `identifier_path` (the named join key, such as `ror`), a
`confidence` in `[0, 1]`, `evidence_refs`, and `exact_id_join`. Candidates must be
ordered by descending confidence, a match with no named identifier path is rejected,
and a promotion to resolved requires the top candidate to be an exact-id join. Both
snapshots are sealed under the federation digest, so an edited field breaks the seal.

## Corpus and readable context

```bash
gather corpus list DIR
gather corpus verify DIR
gather corpus search DIR --terms keyword --json
gather corpus availability DIR
gather corpus context DIR --json
gather corpus context DIR --json --select ROW_REF[:START[:LIMIT]] --expect-digest SHA256
```

`context` inspection returns `gather.readable-corpus/v1`: current corpus
digest, bounded row previews, body status, availability state, and row refs.
Missing, corrupt, unsafe, oversized, or read-budget-exhausted bodies are named and return no excerpt. Inspection verifies only the returned rows when row caps omit the rest of the catalog.

Selection returns `gather.readable-context/v1`: selected source/comment text,
source refs, full body hashes, ranges, omissions, and a deterministic
`selection_digest`. It requires the current digest from inspection so a stale
view cannot be silently selected. It re-hashes selected bodies at read time,
refuses unsafe paths or text over budget, and does not claim the selected source
is true, complete, secret-free, or supports a claim.

Range semantics are text-level. Gather first verifies the stored body against the
exact source text receipt. For readable context, CRLF and CR line endings then
become LF, and `start`/`limit` are Python string character offsets over that
readable view. `sha256`, `verified_sha256`, and `source_sha256` identify the
exact source text; `view_sha256` identifies the full LF-normalized readable view,
and `view_codec` names the transformation. A selected slice does not need to hash
to either full-body value. The selected slice, range, source refs, source/view
hashes, storage status, and omissions are folded into `selection_digest`.

New corpus rows carry a versioned exact-UTF8 storage witness that is folded into
the corpus digest. Rows written before that witness are legacy compatible when
Gather can reconstruct exactly one source text from exact UTF-8 bytes or the old
Windows text writer's LF-to-CRLF expansion. That reconstruction does not prove
old raw object-byte integrity. `--expect-digest` and MCP
`expected_corpus_digest` are the trust boundary for downgrade detection: a pinned
old digest fails after storage metadata is stripped, while recomputing the digest
after mutation accepts the current catalog state.

The reader pins the opened corpus root while loading the catalog and bodies. It does not prove that a caller-resolved `DIR` stayed below an approved workspace parent; hosts that derive a corpus path from workspace authority must bind that parent relationship themselves before calling Gather.

Python hosts that already hold a retained, identity-bound corpus root can call
`inspect_corpus()` or `select_context()` with a same-process
`CorpusRootDescriptor`. Gather duplicates the borrowed fd/HANDLE, validates the
duplicate against the expected `CorpusRootIdentity`, and then uses the same
bounded confined reader. The caller must keep the original descriptor live
through the call. This descriptor handoff is intentionally not exposed through
CLI or MCP, where corpus inputs remain directory strings.

## MCP

Use `gather mcp` when a host needs the tool over stdio. The MCP surface should
stay aligned with the CLI envelope and receipt fields. `gather.context` inspects
stored corpus rows or exports selected readable context with the same type-strict
caps and expected-digest guard as `gather corpus context`.

```bash
gather mcp
```

## Verify

```bash
python -m pytest
python examples/demo.py
python examples/pipeline.py
```

For public/developer delivery checks:

```bash
python -m public_surface_sweeper . --workspace --json
```

## Boundary

Gather may collect material from live sources, but outward-facing receipts
should prefer source references, content hashes, timestamps, and verdicts. Do
not publish raw private payloads, secrets, credentials, or source material whose
license or privacy posture does not allow redistribution.
