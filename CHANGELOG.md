# Changelog

All notable changes to Gather. Versions follow semantic versioning; each minor release was
built behind a feature branch and reviewed before merge.

## Unreleased

### Removed

- Removed the `stealth` capability backend (`backends_stealth.py`) and the
  `curl_cffi` optional dependency. TLS fingerprint impersonation to bypass bot
  detection is out of scope; the default transport identifies itself honestly.

### Video intake pacing and channel runs

- `gather channel URL --store DIR` lists a channel's `videos`, `shorts`, and `streams`
  tabs (or one playlist) with `--flat-playlist` and gathers each entry into the corpus with
  bounded concurrency (default 2) and paced entry starts. A per-pass ledger under
  `DIR/intake/` makes the run resumable, and `summary-<pass>.json` counts entries per tab,
  captions (manual, auto, missing by reason), comments, failures by reason, and retries.
  A run killed mid-write leaves an unfinished last row; the next run drops it and gathers
  that entry again. Any other unreadable row stops the run, before it calls yt-dlp, with
  the line number and exit status 1.
- Separate passes: `--no-captions` gathers metadata and comments without touching the
  caption endpoint; `--captions-only` stores only the transcript item.
- A `gather run` config or an MCP `gather.run` video job takes
  `"captions": "with" | "skip" | "only"` (default `with`). Any other value is a config error,
  raised before any job runs. On MCP the job still needs the `video` network grant,
  whichever pass it asks for.
- The run summary names its files relative to `--store` (a `--summary` outside the store by
  file name) and records the yt-dlp program by file name and a JS runtime without its
  path, so a summary you pass on carries no local path.
- `--timeout` must be above 0, and `--sleep-requests` and `--sleep-subtitles` must be 0 or
  more. Any other value exits 2 before yt-dlp starts.
- Caption intake downloads exactly one track per video, chosen from the info JSON: manual
  first, then the original-language auto-caption (`en-orig`). The old `en.*` pattern fetched
  every English variant and could pick a machine translation; a translation-only video is
  now recorded as missing with the reason `translation-only`.
- HTTP 429, bot checks and YouTube's session rate limit are retried with exponential
  backoff and jitter, bounded by attempts and by total wait. Every retry and final failure
  is logged and recorded. A channel run stops starting new entries once an entry spends its
  whole budget still throttled, and records the rest as stopped.
- The extraction runs with `--ignore-no-formats-error`, so a video whose formats are missing
  still yields its metadata and caption tracks. With that flag yt-dlp reports YouTube's
  playability reason as a warning and exits 0. When the extraction lists no formats, Gather
  reads that warning: a bot check or a session rate limit is retried like an HTTP 429, and
  a private, members-only, age-restricted or removed video is recorded as failed with that
  reason and settled. A geo-blocked or upcoming video is recorded as failed and tried again
  on the next run. None of them stores a metadata item or a "no captions offered" outcome.
- yt-dlp runs with `--js-runtimes node` when it can start `node` (`--js-runtime` overrides),
  and `--sleep-requests` / `--sleep-subtitles` pass through. The check uses the same PATH
  lookup as every child Gather starts, so a `node` only the working folder holds does not
  count.
- Failure messages report yt-dlp's `ERROR` lines instead of the first 160 characters of
  stderr, which was often a version warning.
- A timeout, a missing yt-dlp binary, or a refused start is recorded as a failed call
  (`timeout`, `tool-missing`, `tool-refused`), not an exception.
- Every yt-dlp call (tab listing, extraction, caption download) starts the way every
  other tool does, from an absolute path in a private empty folder with an environment
  allowlist, and carries `--ignore-config`, so no `yt-dlp.conf` changes what it runs.

## 1.9.1 (2026-09-27)

### Security: file sources and MCP path arguments refuse network and device paths

- On Windows, opening a path such as `\\host\share\doc.md` makes the SMB client connect to
  `host` and sign in as the user, which can send the user's NTLM response to whoever runs `host`.
  The `docs`, `pdf`, `ocr` and `transcribe` sources opened any path they were given, and so did
  every path argument on the MCP surface. None of these needed a launch grant. A model connected
  to `gather mcp`, or text it was asked to read, could name a share in `gather.docs`, in a
  `gather.run` job target, config path or `store`, or in the `gather.context`,
  `gather.federation` and `gather.pilot` path arguments. A `store` on a share also writes the
  gathered text there. Affected: 1.6.0 through 1.9.0, when `gather mcp` runs on Windows.
- `gather.localpath` checks the path text before anything opens it. It refuses text that starts
  with two separators of either kind (UNC, `\\?\`, `\\.\`, `\\?\UNC\`, and mixes such as
  `/\host`), text that starts with `\??\`, and any component with a reserved device name (`CON`,
  `PRN`, `AUX`, `NUL`, `CONIN$`, `CONOUT$`, `COM1` to `COM9` and `LPT1` to `LPT9`, including
  the superscript 1, 2 and 3 forms), with or without an extension, trailing dots or spaces.
  `COM0` and `LPT0` are ordinary file names on Windows and still read. Windows rules apply on
  Windows and to Windows-style text on every platform. On Windows it then walks the path without
  following links and refuses a symbolic link or junction whose target is a network or device
  path, before anything opens through it. A relative path is refused when the working folder is
  a share.
- Where it applies: the four file sources on every surface, including each entry of a `docs`
  directory walk; a run config's file-source targets, before any job runs; every MCP path
  argument; a run config's `store` when the config comes through MCP; and a pilot manifest's
  local targets, fixtures and `allowed_local_roots`, where Windows rules apply on every platform
  so a manifest means the same on every machine.
- The MCP call returns `isError: true` with `structuredContent` `{"code": "NON_LOCAL_PATH",
  "retryable": false, "kind": "network" | "device" | "link", "argument": "<name>", "detail":
  "<fixed sentence>"}`. The CLI prints the reason and exits 1. The `gather.docs` `path` and the
  `gather.run` descriptions now say so.
- Changes you may notice: a `\\?\C:\...` long path is refused, so give the plain drive path. A
  share is refused as a source from the CLI too; copy the files to a local folder. A drive letter
  mapped to a share looks local to any check on the text, so Gather cannot see it. The CLI's own
  `--store`, `--output` and `--state` paths, and the `store` in a config run with `gather run`,
  are unchanged.
- `tests/test_nonlocal_paths.py` replaces the filesystem and child-process layer with a spy and
  hands each source and MCP tool one path of each class. On 1.9.0, 81 of its 82 tests failed on
  Windows and 76 on Linux, where POSIX-style names such as `CON` stay ordinary file names by
  design. `tests/test_localpath.py` covers the classifier, the working-folder case and the link
  walk against a fake tree on every platform, and real junctions and symlinks on Windows.
  `tests/test_device_names.py` asks Windows which bare names it opens as devices, so the
  reserved-name list cannot drift from the host. It also checks that `COM0.md` and `LPT0.md`
  read through the `docs` source, the MCP `gather.docs` tool and a pilot manifest.

### Security: a PATH entry that reaches the working folder no longer starts a program there

- 1.9.0 skipped `.` and every other relative PATH entry when it looked up a child program. An
  absolute entry could still reach the working folder: one naming it or a folder below it (a
  project's `node_modules/.bin`, a venv other than the one running Gather), another spelling of
  it (a trailing separator, `..`, letter case), the same folder in quotes, or a junction or
  symlink to it. A program planted there under a tool's name (`pdftotext`, `yt-dlp`,
  `tesseract`, `whisper`, the browser, or a `synthesizer` or `provenance` command) then ran in
  place of the real one. The child also got those entries on its PATH, so a tool that starts
  its own helper by name, as `yt-dlp` starts `ffmpeg`, could start a copy planted there. On
  Windows a drive-relative command such as `C:llm` named a file in the working folder too.
  Affected: every release before 1.9.1. Releases before 1.9.0 started tools by bare name
  through the operating system's own search, which follows these entries as well; on Linux,
  1.8.3 ran the plant through each absolute-entry, link and child-lookup route. 1.9.0 closed the
  current-folder search and `.` entries (see 1.9.0) and left these routes open.
- Gather now vendors safe spawn 1.0.1 (`SAFE_SPAWN_VERSION` 1.0.1, hash-pinned in
  `VENDORED.sha256`). A PATH entry that reaches the working folder, by name or by file identity
  after links are resolved, leaves the lookup and the child's PATH. Each kept entry is searched,
  and handed to the child, as its real folder, so a link repointed after the check cannot change
  what starts. On Windows PATH is read as cmd.exe reads it, an entry whose folder name holds `;`
  leaves, and a bare command name holding `:` is refused. On POSIX an entry written with quotes
  or a leading space counts as relative, and a child PATH the filter empties becomes
  `/bin:/usr/bin`, since an empty PATH means the current folder there. The folder of the Python
  that runs Gather and, on Windows, the Windows, `System32` and `SysWOW64` folders always stay.
- Where the guard narrows: when Gather runs from a filesystem root, or from the home folder or
  a folder above it, only an entry naming that folder itself leaves, because installed tools
  live below it. A working folder that is the folder of the Python that runs Gather, or on
  Windows the Windows, `System32` or `SysWOW64` folder, is not guarded, because Gather already
  runs code from there.
- Changes you may notice: a tool found only inside the working folder is no longer found by
  bare name. Give its absolute path in its `GATHER_<TOOL>` variable, or as the command itself
  for a `synthesizer` or `provenance` command. On Windows, a conda environment created inside
  the working folder keeps only its root folder: its `Scripts` and `Library\bin` folders leave,
  so set `GATHER_PDFTOTEXT`, `GATHER_TESSERACT`, `GATHER_YT_DLP` or `GATHER_WHISPER` to the
  tool's full path, or create the environment outside the project. On Windows, a PATH entry
  with an unmatched double quote hides every entry after it, as it does in cmd.exe; remove the
  stray quote or set the `GATHER_<TOOL>` variable. A drive-relative command is refused as not
  found.
  The child's PATH names real folders, so a version manager's `current` link reaches it
  resolved. Each tool start now reads every PATH entry and the folders above it. That took
  about 20 to 60 ms per start on Windows, and a median of about 1.4 s under WSL, where PATH
  inherits the Windows folders.
- `tests/test_spawn_working_folder.py` plants decoys in the working folder and a folder below
  it, puts the real tool later on PATH, and reaches the working folder by each route above. On
  1.9.0, 13 of its 16 tests failed on Windows and 9 on Linux, each because the planted program
  ran. On 1.8.3 on Linux, 7 route tests failed the same way. Its three controls keep a sibling
  folder whose name starts with the working folder's, a folder holding the working folder, and
  an override inside the working folder; they pass on 1.9.0 and 1.9.1. `tests/test_vendored.py`
  now names a 1.0.0 copy as superseded.
- CI now runs the child-spawn tests on Windows too, where the junction, letter-case and
  drive-relative routes live. Under CI, a Windows run that cannot build a real `.exe` decoy
  fails these tests instead of skipping them.

## 1.9.0 (2026-09-26)

### Security: launch-only grants on the MCP surface

- `gather.run` took a config from tool arguments and ran whatever `synthesizer` or
  `provenance` command it named, fetched any network source it listed, and read any
  environment variable named as `auth_env` and sent its value as a bearer token to the host
  in the config. A model, or text a model was asked to read, could run commands and send a
  secret off the machine with one tool call. `gather.pilot` had the same exposure through a
  live manifest (`auth_env`, and a `browser` option naming any executable). Affected: every
  release with the MCP `gather.run` or `gather.pilot` tool, up to and including 1.8.3.
- These now need a grant set at launch. `GATHER_ALLOW_EXEC` (`gather mcp --allow-exec`) names
  the commands a config may run. `GATHER_ALLOW_NETWORK` (`--allow-network`) names the network
  sources. `GATHER_AUTH_ENV_ALLOW` (`--auth-env NAME@HOST`) binds each credential variable to
  the one host it may be sent to, over `https` only. A pilot manifest's `browser` option other
  than `chromium`, or `no_sandbox`, needs that browser named in `GATHER_ALLOW_EXEC`.
- Without the grant the call returns `isError: true` with `structuredContent`
  `{"code": "GRANT_REQUIRED", "retryable": false, "setup": "<VARIABLE>", "detail": "<fixed
  sentence>"}` before anything runs, connects or reads a credential. The server reads grants
  once at startup; nothing in a config, manifest or tool call widens them. A pilot refresh
  checks the grants on the same read of the stored manifest it captures from.
- Tool descriptions changed: `gather.run` and `gather.pilot` now say which inputs need a launch
  grant, so a host sees why a call returns `GRANT_REQUIRED`.
- Breaking for MCP hosts that relied on the old behavior: add the grant to the server's launch
  configuration. The CLI and the Python API run the operator's own config and are unchanged.

### Security: child programs start from an absolute path in a private folder

- `pdftotext`, `yt-dlp`, `tesseract`, `whisper` and the headless browser started by bare name
  from the server's working folder. On Windows a same-named `.exe` in that folder ran in place
  of the real tool, and on any platform a `.` entry on PATH did the same. `yt-dlp` also read a
  `yt-dlp.conf` from that folder, and a config can carry `--exec`. The `synthesizer` and
  `provenance` commands had the same lookup. Affected: every release up to and including 1.8.3.
- Every child now starts through `gather.spawn`, which calls the vendored safe spawn helper
  (`SAFE_SPAWN_VERSION` 1.0.0, hash-pinned in `VENDORED.sha256`). The program resolves to an
  absolute path (`GATHER_<TOOL>` overrides win; relative and empty PATH entries never count),
  runs in a new private empty folder, and sees an environment allowlist instead of Gather's
  whole environment. `yt-dlp` gets `--ignore-config`. On Windows the child also gets
  `NoDefaultCurrentDirectoryInExePath=1`, and a batch-file target refuses cmd.exe
  metacharacters. Output stays bytes, so receipts hash exactly what the tool wrote.
- Changes you may notice: a command given as a relative path is refused; a synthesizer that
  reads its API key from the environment needs `GATHER_CHILD_ENV=KEY_NAME`; `yt-dlp` no longer
  reads your user `yt-dlp.conf`; a `python -m` provenance command must be installed, not only
  present in the working folder.
- `tests/test_spawn_children.py` plants a decoy named like each child (a real `.exe` on
  Windows) in the caller's folder with `.` on PATH, a fake API key in the environment and a
  `yt-dlp.conf`. 18 of its 19 first tests failed on the unfixed code. With `yt-dlp` installed,
  a real-tool test shows a planted `yt-dlp.conf` taking effect without the fix and having no
  effect through `VideoSource`.

### Release workflow

- The workflow grants nothing by default. `build` reads the repository, `publish` holds only
  `id-token: write` for trusted publishing, and a new `github-release` job holds only
  `contents: write`. Checkouts drop the token after cloning.
- The PyPI upload uses `skip-existing: true`, so a re-run after a partial upload completes.
- The build checks the tag against the package version and the vendored helper in the wheel
  against `VENDORED.sha256`, then writes `SHA256SUMS.txt` for the wheel and the sdist. The
  `github-release` job verifies those sums and creates the GitHub Release with the wheel, the
  sdist and `SHA256SUMS.txt` attached, or refreshes its files on a re-run. Before this, the
  release and its checksum file were made by hand.

## 1.8.3 (2026-09-23)

### Catalog line breaks

- Readable context (`inspect_corpus`, `select_context` and their MCP tools) now splits
  `catalog.jsonl` on LF, CRLF and CR only, the rule `Corpus.rows` reads by. It used
  `str.splitlines`, which also breaks on U+2028, U+2029 and U+0085. The catalog writer leaves
  those characters unescaped inside JSON strings, so one title such as a misdecoded
  Windows-1252 ellipsis made the context surface refuse a corpus that `verify` accepts.
- A regression test stores titles carrying each of those characters, rewrites the catalog
  with LF, CRLF and lone-CR row terminators, and checks that `Corpus.rows` and
  `inspect_corpus` read the same rows. The store newline test now also checks that the
  object bytes on disk hash to the catalog `sha256`.

### Presentation parity

- README now exposes the current source version, operator commands, and the
  boundary between exact source-byte receipts and optional source adapters.

## 1.8.2 (2026-09-10)

### MCP scope clarity

- Documentation now states that Gather MCP scope filtering is an advisory host
  boundary over declared source scopes, not a private-data scanner or universal
  access-control substitute.

## 1.8.1 (2026-09-09)

### POSIX descriptor authority admission

- Linux/WSL confined corpus readers now reject filesystem mounts whose retained directory fd semantics cannot safely anchor child opens across rename/replacement, currently observed on WSL Windows-drive 9p/v9fs mounts.
- The rejection happens while establishing each opened corpus, descendant directory, or catalog/body file descriptor, before reading `catalog.jsonl` or body objects from that descriptor, and uses the existing typed `UNSAFE_PATH` public failure boundary.
- Native Windows and native Linux/WSL filesystem roots keep the descriptor-handoff behavior from 1.8.0; POSIX platforms without Linux fd mount-type support keep the existing openat/no-follow/type checks without an unsupported-mount detection claim. CLI and MCP still accept path strings only, with no path fallback for unsupported retained authority.

## 1.8.0 (2026-09-08)

### Readable context descriptor handoff

- Python context readers now accept a same-process `CorpusRootDescriptor` so a host that already retained a corpus root fd/HANDLE can pass that authority into Gather without reopening the root path.
- Gather duplicates and identity-checks the borrowed descriptor before reading `catalog.jsonl` or body objects, keeps caller-owned descriptors open, and continues to use the existing bounded confined reader for all catalog/body reads.
- CLI and MCP context surfaces remain path-string based; descriptor handoff is not serialized across process or JSON boundaries and still does not prove source truth, claim support, coverage completeness, Flywheel deployment, or caller workspace-parent resolution.

## 1.7.1 (2026-09-08)

### Corpus newline integrity

- New corpus object writes now use exact UTF-8 bytes, avoiding platform text-mode newline translation.
- New catalog rows carry a versioned storage witness folded into the corpus digest; consumers detect witness stripping or codec changes when they pin the prior digest through `--expect-digest` / `expected_corpus_digest`.
- Legacy rows without a storage witness can reconstruct source text from exact UTF-8 bytes or the old Windows text writer's LF-to-CRLF expansion without rewriting historical objects or claiming old raw-byte integrity.
- Adding a receipt now refuses a corrupt preexisting object at the content-addressed path before appending to the catalog; valid legacy objects are still reused without rewriting.
- Readable context now distinguishes exact source identity (`verified_sha256` / `source_sha256`) from the LF-normalized readable view (`view_sha256` / `view_codec`) while preserving the existing v1 payload fields.

## 1.7.0 (2026-09-08)

### Readable context selection

A first-class corpus-to-context boundary for humans and agents that need selected source text, not only catalog hashes.

- Python API: `inspect_corpus`, `select_context`, and `row_ref` expose bounded verified excerpts, explicit row refs, body status, availability, and selected private context payloads.
- CLI parity: `gather corpus context DIR --json` inspects readable row excerpts; adding `--select ROW_REF[:START[:LIMIT]] --expect-digest SHA256` exports selected context guarded by the current corpus digest.
- MCP parity: `gather.context` provides the same inspect/select payloads for stdio hosts.
- Integrity and privacy boundaries: context selection reads and re-hashes only bounded inspected or selected bodies through a confined corpus-layout reader, refuses stale corpus digests, unsafe object paths, oversized bodies/catalogs, missing/corrupt bodies, and selected text over budget, binds selected text/ranges/source refs/full body hashes into `selection_digest`, pins the opened corpus root across catalog/body reads, and reports that acquisition does not prove source truth, claim support, coverage completeness, downstream model use, caller workspace-parent resolution, or absence of sensitive text in the selected source material.

### Accountable pilot evidence engine

A retained-capability research pilot over Gather's existing adapters. One
closed manifest drives a source-isolated capture into a content-addressed
corpus; the result is a redacted report, a hash-chained receipt, a monitored
change ledger with archived history, and deterministic shared or full bundles
any third party re-verifies offline.

- `gather pilot run|refresh|verify|bundle` CLI command group with typed exit
  semantics (manifest refusal `2`, required-source/verification failure `1`).
- `gather.pilot` MCP tool (run, refresh, verify, bundle) with a closed schema.
- Closed pilot-manifest validation: unknown fields, wildcard hosts, ports,
  userinfo, IP literals, `..`/absolute paths, and credential values are
  rejected. Offline network adapters require a fixture; browser is opt-in.
- Source-isolated orchestrator: every source gets exactly one outcome; partial
  success is never erased; diagnostics are bounded and credential-scrubbed.
- Canonical report (`gather.pilot-report/1`), self-contained semantic HTML, and
  a closed `gather.pilot-receipt/1` binding manifest, report JSON/HTML, corpus,
  monitor ledger, and history chain.
- `refresh_pilot`: verify-first, archive the prior triplet, re-capture monitored
  sources, run one `monitor_pass`, write a new current view (NEW/CHANGED/UNCHANGED).
- Deterministic shared and full bundles (`gather.pilot-bundle/1`): `ZIP_STORED`,
  fixed timestamps, a non-recursive bundle digest; shared refuses private content.
- Representative offline showcase (three missions, six adapters) with original
  synthetic fixtures and a checked-in redacted sample pinned against drift.

## 1.6.1 (2026-07-07)

Docs and visual-identity release; no engine code changes since 1.6.0.

- Visual-identity refresh: new spectrum banner (`.github/assets/banner.svg`) and a
  feature-first README header, with the delivery contract in `tests/test_docs.py`
  updated to pin the new assets.
- Docs overhaul: the README body rewritten feature-first, and a new
  `docs/INTRODUCTION.md` walkthrough covering the current toolkit end to end.
- Live PyPI downloads badge added to the README.

## 1.6.0

The web-data engine release (2026-07-04): a capability-superset web toolkit carrying gather's
receipt discipline, plus scholarly-graph federation and source-federation contracts. 368+ tests;
ruff + mypy clean.

- **Web-data engine (1.6.0):** a capability-superset web toolkit carrying gather's receipt
  discipline, standing against browser-use, Scrapling, crawlee, and firecrawl on features and
  speed. `gather.dom`/`gather.extract` turn HTML into Markdown plus a per-block provenance
  receipt (source-node path + content hash); `gather.track` relocates a scraped element across
  page versions with a witnessed MATCH/RELOCATED/DRIFT/GONE verdict; `gather.fetch` returns a
  re-verifiable FetchReceipt (bytes + headers digest, redirect chain, conditional GET,
  retry/backoff) over the existing SSRF-guarded edge; `gather.crawl` is a concurrent, resumable
  crawler (robots, sitemap, dedup, per-host throttle) emitting an append-only hash-chained
  ledger; `gather.schema_extract` binds schema fields to source nodes and rejects any
  LLM-proposed value not grounded in the fetched content; `gather.search` turns a query into
  fetchable leads through a pluggable provider (honest UNVERIFIABLE with none). Optional
  capability backends register when installed: `gather[fast]` (lxml, ~2x parse),
  `gather[browser]` (Playwright JS render), `gather[stealth]` (curl_cffi TLS impersonation); a
  missing capability degrades to UNVERIFIABLE, never a fake. `gather.interop` maps these receipts
  onto the organ-bundle spine (validated against proof-surface's real validator). New CLI:
  `gather caps|extract|markdown|crawl`. Full suite 368+ tests; ruff + mypy clean.
- `gather.scholar`: a scholarly-graph federation adapter unifying OpenAlex, Semantic Scholar,
  and Crossref into one intake. Pure per-provider parsers (`parse_openalex`,
  `parse_semanticscholar`, `parse_crossref`) normalize each graph's shape onto one
  provider-neutral `ScholarWork` (OpenAlex abstracts reconstructed from the inverted index);
  `ScholarSource` is the isolated impure edge with an injectable fetcher, so the whole
  federation is tested offline over recorded fixtures. Citation edges (references and citations)
  are first-class provenance: `citation_edges` turns each into a re-checkable receipt (method
  `citation-edge`, registered DIRECT on the method ladder) recording which provider asserted the
  link, deduped by `(from, to, direction, provider)` and sealed into the digest alongside the
  papers. `federate` joins works by normalized DOI (`normalize_doi` strips URL/`doi:` prefixes
  and lowercases) into one unified `compiled` item whose `derived_from` points back at every
  provider's contribution (no provenance dropped); a DOI is the only join key, never a fuzzy
  title match, and a DOI-less work stays its own record. CLI: `gather scholar QUERY
  [--providers ...] [--no-federate] [--edges] [--json]`; `--edges` folds the citation edges into
  the same witnessed digest as the papers, so the seal covers the graph, not just the nodes.
- `gather.federation`: the source-federation registry contract. A registry row is a closed
  nine-field shape (`id`, `system`, `family`, `domain`, `access`, `adapter`, `url`, `scope`,
  `priority`) with closed vocabularies for the access policy (`open`, `key_required`,
  `rate_limited`, `restricted_or_registered`, `endpoint_alias_needed`, `source_lead_only`,
  `account_required`) and for per-probe capture statuses (`GATHER_VERIFIED` plus five typed
  warnings). Registry snapshots fold under the existing digest seal (the availability-rung
  precedent): each row is fingerprinted whole, so editing a sealed row breaks `verify_digest`.
  `join()` derives one evidence status per source from its capture statuses; a source with no
  captures reports `SOURCE_LEAD_ONLY`, never availability. Unknown tokens and statuses are
  typed rejections.
- `gather.federation_policy`: the pure adapter policy compiler (`compile_plan`, one
  deterministic capture plan per access token, unknown token refused) and the claims guard
  (`guard_claim`, whitelist with default deny). Six known-bad claim patterns are refused by
  name and pinned by negative fixtures that must reject: `source_count_as_world_coverage`,
  `registry_listing_as_endpoint_availability`, `metadata_as_full_text`,
  `closed_key_source_as_available`, `empty_capture_as_match`, and
  `route_failure_as_source_absence`.
- CLI/MCP surface: `gather federation validate|plan FILE [--json]` and the `gather.federation`
  MCP tool (inline rows or a registry path) share the `gather.federation-registry/v1` payload;
  the status envelope advertises both. No live probes and no source data ship with the
  machinery.
- `gather.federation_receipt`: two federation decisions treated as sealed claim surfaces, each
  folded under the federation seal so an edited field breaks `verify_digest`. A retry/backoff
  policy rule (`validate_policy_rule`, `policy_rule_digest`) carries a provenance capture ref
  and a `failure_class` mapped to one typed verdict (`429` to `retryable_source_lead`, `403` to
  `access_escalation`, `503` to `retry_after`); a rule with no capture ref, an unknown failure
  class, or a `superseded` flag is a typed rejection. An entity-resolution match
  (`validate_entity_match`, `resolve_entity`, `entity_match_digest`) carries a named
  `identifier_path`, a unit-interval `confidence`, and `evidence_refs`; a match with no named
  identifier path, a ranking out of confidence order, or a promotion to resolved on a fuzzy name
  match rather than an exact-id join is a typed rejection. New `gather federation policy|entity
  FILE [--json]` CLI actions share the `gather.federation-policy/v1` and
  `gather.federation-entity/v1` payloads.
- `gather.availability`: a seal-covered availability rung per source record. `witness_availability`
  checks each catalog row through a probe (default: the corpus's own store; a live re-fetch probe
  plugs in through the seam) and seals `{status, checked_at, sha256}` into the digest, so an
  availability claim cannot be edited after witnessing without breaking the seal. Re-verification
  (`assess_availability`) reports typed outcomes gated on the content-hash binding, never the
  status string: AVAILABLE only when the bound hash matches the receipt, CHANGED when the source
  answered with different content, UNAVAILABLE when it did not answer, and UNWITNESSED for a
  legacy record without the rung (which still verifies, but is never reported available). New
  `corpus availability` CLI action, exiting non-zero unless every record assesses AVAILABLE.
- CLI compatibility: `python -m gather` and `python -m gather.cli` now dispatch the normal Gather
  CLI from source checkouts, so module-mode MCP hosts and harnesses can use the same command
  surface as the installed `gather` script.
- Enterprise readiness: adds `docs/ENTERPRISE-READINESS.md` for context envelopes, action receipts, readability gates, and host-neutral operation.
- MCP host-neutral run configs: `gather.run` now accepts either a local config path or an inline config object, so OpenAI, Anthropic, IDE, TUI, and app hosts do not need to stage temporary files before running witnessed intake.
- Operator surface: the status payload now advertises shared Project Telos CLI/MCP/plugin/IDE/TUI/app contracts for enterprise, research, creative, scientific, and education workflows.

Operator-spine housekeeping for Project Telos presentation parity.

- README: adds the shared forward-facing status block, current CI badge, and consistent five-flagship navigation.
- Status payload: exposes current operator commands, MCP tool names, and a plain current-status string under `native`.
- CLI/MCP surface: records the Project Telos `status`, `doctor`, `demo`, and `mcp` operator surfaces now present on the command line.
- CLI/MCP payloads: share the `gather.catalog-digest/v1` envelope for catalog rows, digest receipts, dropped-counts, and digest verification status.
- MCP tools: documents native availability for `gather.status`, `gather.doctor`, `gather.docs`, `gather.arxiv`, and `gather.run`.
- CI repair: the run-config synthesizer is typed against the shared `Synthesizer` protocol so the post-operator-spine code remains mypy-clean.

## 1.5.0

Organic completion. A final multi-lens whole-system review (correctness, security, docs) across
all post-1.0 growth, its findings fixed. No new adapters; the milestone is that the organ is
complete and its accountability claims hold end to end.

- Security: the video edge passes its target after `--` (the last argv-injection gap closed, uniform
  with the other tool edges); `decode_body` falls back to utf-8 on a malformed charset; XML-safety
  regression tests pin that the feed/arxiv parsers do not resolve external entities (XXE) and fail
  fast on an entity-expansion blowup.
- Corruption survival: `corpus verify` reports a field-missing row as CORRUPT instead of crashing,
  and `recall` skips it as CORRUPT, so one malformed line never hides the rest; the `corpus` command
  surfaces a malformed catalog as a clean error, not a traceback.
- `corpus prune` refuses to delete when the catalog is empty but bodies exist (a torn-write state),
  rather than removing every body.

## 1.4.0

The last committed roadmap item: the digest composed with an external origin verdict. (Remaining
items, e.g. corpus indexing, are optional scale work, not missing function.)

- `gather.provenance`: the `ProvenanceProvider` seam, which composes an EXTERNAL origin verdict for
  an item (is it forged, a re-encode, authentic) beyond Gather's own content receipt. The default
  `NullProvenanceProvider` makes no claim (Gather stands alone); `SubprocessProvenanceProvider`
  shells to an external provenance organ (request on stdin, JSON verdict on stdout, errors reported
  not raised), e.g. provenance-sensorium.
- `gather_run` accepts a `provenance` provider; each digested item's origin verdict is recorded in
  the `RunRecord` (a new sealed `origins` field) and re-checkable from disk. `gather run` selects it
  via a `provenance` command in its config.

## 1.3.0

- Operating a corpus over time: `corpus stats` (a read-only summary, item and distinct-body counts
  by source/kind/method) and `corpus prune` (find, and with `--apply` delete, orphan object files
  left by a crash between a body write and its catalog row). Prune is report-only by default, aborts
  on a malformed catalog, skips `.tmp` staging files (which may be a concurrent write), returns the
  list of deleted paths as an audit trail, and must run with no concurrent writer. It never deletes
  a referenced body.

## 1.2.0

- `gather.model.SubprocessSynthesizer`: the real model edge for the `Synthesizer` seam (the default
  only compiled). It shells to an operator-configured model CLI to infer a statement, with the
  prompt (built from gathered content) on STDIN never the argv, and is stamped `synthesized` with
  `derived_from` set, so a real inference is honestly distinguished from a compilation. `gather run`
  accepts a `synthesizer` command in its config to use it.

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
  http and browser edges. The new tool paths (OCR, transcribe) are resolved to absolute paths so a
  filename starting with `-` cannot be read as a flag.
- The browser edge is honest about its limits: the guard covers only the initial navigation (a
  rendered browser then follows its own redirects and sub-requests unguarded), and the Chromium
  sandbox is left on by default (`no_sandbox` is opt-in). See the threat model in ARCHITECTURE.md.

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
