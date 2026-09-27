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


## Video and channel intake

`gather video` and `gather channel` run `yt-dlp`: the one on PATH, the absolute path in
`GATHER_YT_DLP`, or the bare name or absolute path given with `--yt-dlp`. Every call
(tab listing, extraction, caption download) starts the way every other tool does (see
[External tools](#external-tools)) and carries `--ignore-config`.

```bash
gather video URL --comments --store DIR           # metadata, one caption track, comments
gather video URL --no-captions --comments         # metadata and comments only
gather video URL --captions-only --store DIR      # the transcript item only
gather channel https://www.youtube.com/@name --store DIR --no-captions --comments
gather channel https://www.youtube.com/@name --store DIR --captions-only     --concurrency 1 --interval 15 --jitter 5 --sleep-subtitles 5
gather channel "https://www.youtube.com/playlist?list=ID" --store DIR --no-captions
```

- **One caption track per video.** Gather reads the track list from the info JSON and
  downloads exactly one track: a manual track first, then the original-language
  auto-caption (`en-orig`). A machine-translated track is recorded as missing with the
  reason `translation-only`, never stored as a transcript. `--caption-langs en,sr` sets
  the language order.
- **JavaScript runtime.** `--js-runtime auto` (the default) passes `--js-runtimes node`
  when yt-dlp can start `node`: Gather looks it up the way it looks up its own tools, so a
  `node` that only your working folder holds does not count. `none` turns it off; any
  other value is passed through.
- **Pacing and backoff.** `--sleep-requests` and `--sleep-subtitles` pass through to
  yt-dlp. On HTTP 429 or a bot check, Gather retries with exponential backoff and jitter,
  bounded by `--retries` (attempts, counting the first), `--backoff-cap` (one wait), and
  `--backoff-budget` (total wait per call). Every retry is logged to stderr and recorded.
- **Real failure lines.** A failed call reports its `ERROR` lines, not a leading version
  or runtime warning.
- **Channel runs.** `gather channel` lists the `videos`, `shorts`, and `streams` tabs
  (`--tabs`) with `--flat-playlist`, gathers each entry with `--concurrency` workers
  (default 2), and spaces entry starts by `--interval` plus up to `--jitter` seconds. It
  appends one row per entry to `DIR/intake/ledger-<pass>.jsonl` and skips settled entries
  on the next run, so a stopped run resumes. When an entry spends its whole backoff budget
  still throttled, the run stops starting new entries and records the rest as `stopped`.
  If a run was killed mid-write, the next run drops the unfinished last row and gathers
  that entry again. Any other unreadable row stops the run before it calls yt-dlp and
  names the line.
- **Run summary.** `DIR/intake/summary-<pass>.json` counts entries listed per tab,
  outcomes, captions (manual, auto, missing by reason), comments, failures by reason, and
  retries, for this run and for the whole pass. The ledger and summary carry counts only,
  never comment text or commenter names.

Exit codes for `gather channel`: `0` when every pending entry was attempted; `1` when
the pass ledger cannot be read, listing failed, or the pass stopped on throttling; `2` on
bad options.

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
through the call. On Linux/WSL filesystems where retained directory fds cannot
supply stable confined reads, currently including WSL Windows-drive 9p/v9fs
mounts, Gather refuses opened corpus, descendant directory, and catalog/body file
descriptors before reading `catalog.jsonl` or body objects. This
descriptor handoff is intentionally not exposed through CLI or MCP, where
corpus inputs remain directory strings.

## MCP

Use `gather mcp` when a host needs the tool over stdio. The MCP surface should
stay aligned with the CLI envelope and receipt fields. `gather.context` inspects
stored corpus rows or exports selected readable context with the same type-strict
caps and expected-digest guard as `gather corpus context`.
For catalog tools, `scope` is a post-fetch content filter that keeps rows whose title or body contains any term as a case-insensitive substring, so `verified: true` on an empty scoped catalog means the returned digest verified after filtering, not that acquisition returned no source records.

```bash
gather mcp
```

### Launch grants

A `gather.run` config and a `gather.pilot` manifest can come from tool arguments,
so the model controls them. Anything in them that runs a command, reaches the
network or sends a credential needs a grant you set when you add the server to
the host. With no grant the call returns `GRANT_REQUIRED` and names the variable
to set. Nothing starts, connects or reads the credential first.

| Grant | Flag | Covers |
|:-|:-|:-|
| `GATHER_ALLOW_EXEC=llm,/opt/prov/check` | `--allow-exec COMMAND` | the `synthesizer` and `provenance` commands a config may run, matched on the command's first element; a pilot `browser` option other than `chromium`, or `no_sandbox` |
| `GATHER_ALLOW_NETWORK=web,feed` or `all` | `--allow-network SOURCE` | the network sources a config or a live pilot manifest may use: `web`, `feed`, `arxiv`, `scholar`, `video`, `api`, `browser` |
| `GATHER_AUTH_ENV_ALLOW=GATHER_API_TOKEN@api.example.com` | `--auth-env NAME@HOST` | the `api` source may read variable `NAME` only to send it over `https` to that exact host |

Grant the program itself, not an interpreter: the model chooses the rest of the
command line, so granting `python` or a shell grants arbitrary code.

The server reads grants once, at launch. A later change to its environment
grants nothing, and no field in a config, a manifest or a tool call is read as a
grant. Local sources (`docs`, `pdf`, `ocr`, `transcribe`) and the dedicated
`gather.arxiv` tool need no grant. The CLI (`gather run CONFIG`) and the Python
API run your own config and keep full trust.

```bash
gather mcp --allow-network arxiv --allow-exec llm
```

### Local paths only

On Windows, a path such as `\\host\share\notes.md` makes the machine connect to
`host` and sign in as you, which can send your NTLM credentials to whoever runs
`host`. Gather refuses network and device paths before it opens anything:

- the `docs`, `pdf`, `ocr` and `transcribe` sources, on every surface, including
  each entry of a `docs` directory walk;
- every MCP path argument: `gather.docs` `path`, `gather.run` `config` or
  `config_path`, `gather.federation` `registry`, `gather.context` `corpus`, and
  `gather.pilot` `manifest`, `output` and `bundle_output`;
- a run config's file-source targets, checked before any job runs, and its
  `store` when the config comes through MCP;
- a pilot manifest's local targets, fixtures and `allowed_local_roots`.

A path is refused when it starts with two separators of either kind (`\\host`,
`//host`, `\\?\`, `\\.\`, `\\?\UNC\`, or a mix such as `/\host`), starts with
`\??\`, or has a component with a reserved device name: `CON`, `PRN`, `AUX`,
`NUL`, `CONIN$`, `CONOUT$`, `COM1` to `COM9` or `LPT1` to `LPT9` (including
the superscript 1, 2 and 3 forms), with or without an extension, trailing dots
or spaces. `COM0` and `LPT0` are ordinary file names on Windows and still read.
Windows rules apply on Windows and to Windows-style text (a backslash or a drive
prefix) on every platform. A pilot manifest applies them everywhere, so it means
the same on every machine. On Windows, Gather also walks the path without
following links and refuses a symbolic link or junction whose target is a
network or device path, and a relative path when the working folder is a share.

The MCP call returns `isError: true` with `structuredContent`
`{"code": "NON_LOCAL_PATH", "retryable": false, "kind": "network", "argument": "path", "detail": "<fixed sentence>"}`,
where `kind` is `network`, `device` or `link`. The CLI prints the reason and
exits 1.

Limits:

- A drive letter mapped to a share (`Z:`) looks like any local drive, so no
  check on the text can see it.
- A `\\?\C:\...` long path is refused. Give the plain drive path, and turn on
  Windows long path support if you need paths over 260 characters.
- The CLI's own `--store`, `--output` and `--state` paths, and the `store` in a
  config you run with `gather run`, are your choice and are not checked.

## External tools

The `pdf`, `ocr`, `transcribe`, `video` and `browser` adapters, and a run's
`synthesizer` and `provenance` commands, start another program. Gather starts
each one the same way:

- It resolves the program to an absolute path. `GATHER_PDFTOTEXT`,
  `GATHER_TESSERACT`, `GATHER_WHISPER`, `GATHER_YT_DLP` and `GATHER_CHROMIUM`
  take an absolute path and win over PATH. The PATH lookup skips `.` and every
  other relative entry. It also skips every entry that reaches your working
  folder: the folder itself, a folder below it, a junction or symlink to either,
  and other spellings such as a trailing separator, `..` or quotes. So a file
  named like the tool in your working folder does not run, except in the two
  cases below. A command given as a relative path (`./tools/synth`) is refused,
  and so is a Windows drive-relative name (`C:synth`); give a bare name on PATH
  or an absolute path.
- The guard narrows in two cases. When Gather runs from a filesystem root, or
  from your home folder or a folder above it, only an entry naming that folder
  itself leaves. Folders below it stay, because installed tools live there.
  When the working folder is the folder of the Python that runs Gather, or on
  Windows the Windows, `System32` or `SysWOW64` folder, no entry leaves for it,
  because Gather already runs code from that folder.
- To run a tool that lives inside your working folder, such as one in a
  project's `node_modules/.bin`, give its absolute path: in its `GATHER_<TOOL>`
  variable, or as the command itself for a `synthesizer` or `provenance`
  command. The folder of the Python that runs Gather always stays on PATH, so
  when Gather runs from a venv inside your project, that venv keeps its tools.
- On Windows, a conda environment created inside the working folder keeps only
  its root folder, where its `python.exe` lives. Its `Scripts` and
  `Library\bin` folders, where conda puts command-line tools, leave. Set
  `GATHER_PDFTOTEXT`, `GATHER_TESSERACT`, `GATHER_YT_DLP` or `GATHER_WHISPER`
  to the tool's full path, or create the environment outside the project.
- On Windows, PATH is read as cmd.exe reads it. An entry with an unmatched
  double quote hides every entry after it, as it does in cmd.exe, so a tool in a
  later folder is reported as not found. Remove the stray quote, or set the
  tool's `GATHER_<TOOL>` variable.
- It starts the program in a new private empty folder, so the program reads no
  configuration from your working folder. `yt-dlp` also gets `--ignore-config`,
  so no `yt-dlp.conf` changes what it runs, including your user config.
- It passes a short environment allowlist (`PATH`, the system and home
  variables, and for `yt-dlp` and the browser the proxy and CA variables).
  Name anything else a program needs, such as a synthesizer's API key, in
  `GATHER_CHILD_ENV=NAME1,NAME2`. The program's `PATH` holds only the entries
  the lookup kept, each as its real folder, so a program that starts its own
  helper by name, as `yt-dlp` starts `ffmpeg`, cannot reach your working
  folder either.
- A Python command gets `-P`, so it cannot import a module planted beside it.
  Install the module a `python -m` provenance command runs.

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
