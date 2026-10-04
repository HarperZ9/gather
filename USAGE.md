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
gather channel https://www.youtube.com/@name --store DIR --captions-only --concurrency 1 --interval 15 --jitter 5 --sleep-subtitles 5
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
- **What yt-dlp sends.** Gather passes no flag that sets a User-Agent, a cookie, a proxy
  or an impersonation target. yt-dlp marks each YouTube caption track for browser
  impersonation, and Gather removes that mark before the caption download, so the track
  is fetched as yt-dlp itself. yt-dlp still sends its own default headers, including a
  desktop Chrome User-Agent whose version it picks each run. For some sites other than
  YouTube, its extractors ask for impersonation while they extract, and yt-dlp has no
  flag that turns this off. It happens only where yt-dlp can import `curl_cffi`;
  `yt-dlp --list-impersonate-targets` marks every target unavailable when it cannot.
- **Pacing and backoff.** `--sleep-requests` and `--sleep-subtitles` pass through to
  yt-dlp and take 0 or more seconds. `--timeout` takes more than 0. On HTTP 429 or
  YouTube's session rate limit, Gather retries with exponential backoff and jitter,
  bounded by `--retries` (attempts, counting the first), `--backoff-cap` (one wait), and
  `--backoff-budget` (total wait per call). Every retry is logged to stderr and recorded.
- **Bot checks.** When YouTube asks for a bot check ("confirm you're not a bot"), Gather
  stops. It does not retry the call or try to answer the check. The failure is recorded
  with the code `bot-check`, and its reason starts with "YouTube asked for a bot check, and
  gather stopped", then gives yt-dlp's own line. On the extraction, `gather video` exits 1;
  on the caption download it keeps the metadata and logs the check. `gather channel` stops
  the pass at the first bot check, whatever `--max-throttled` says, records the remaining
  entries as `stopped`, and exits 1. With `--concurrency` above 1, an entry another worker
  had already started still runs to its end. The entry that met the check is settled, so a
  resumed run does not ask for it again. When you choose to try that video again, ask for
  it by name: `gather video URL --store DIR` with the pass's flags. A bot check while
  listing a tab stops the run before any entry is gathered.
- **Why a video served nothing.** The extraction runs with `--ignore-no-formats-error`, so
  a video whose formats are missing still gives its metadata and caption tracks. That flag
  also makes yt-dlp print YouTube's playability reason as a `WARNING` and exit 0. When the
  extraction lists no formats, Gather reads that line. A session rate limit is retried and
  a bot check stops, both as above. A private, members-only, age-restricted or removed
  video is recorded as failed with its reason and skipped on the next run. A geo-blocked or
  upcoming video is recorded as failed and tried again on the next run.
- **Real failure lines.** A failed call reports its `ERROR` lines, not a leading version
  or runtime warning. A yt-dlp that cannot start is recorded as `tool-missing`, and one
  Gather will not start with these arguments as `tool-refused`. On Windows a `yt-dlp.cmd`
  or `.bat` shim gets `tool-refused` on the caption call, because the output template
  holds `%`, which cmd.exe would expand. Point `GATHER_YT_DLP` at `yt-dlp.exe` instead.
- **Channel runs.** `gather channel` lists the `videos`, `shorts`, and `streams` tabs
  (`--tabs`) with `--flat-playlist`, gathers each entry with `--concurrency` workers
  (default 2), and spaces entry starts by `--interval` plus up to `--jitter` seconds. It
  appends one row per entry to `DIR/intake/ledger-<pass>.jsonl` and skips settled entries
  on the next run, so a stopped run resumes. When an entry spends its whole backoff budget
  still throttled, the run stops starting new entries and records the rest as `stopped`.
  A bot check stops the run the same way, on the first entry that meets one.
  If a run was killed mid-write, the next run drops the unfinished last row and gathers
  that entry again. Any other unreadable row stops the run before it calls yt-dlp and
  names the line.
- **Run summary.** `DIR/intake/summary-<pass>.json` counts entries listed per tab,
  outcomes, captions (manual, auto, missing by reason), comments, failures by reason, and
  retries, for this run and for the whole pass. The ledger and summary carry counts only,
  never comment text or commenter names. The summary names its files relative to `DIR`
  and the yt-dlp program by file name, so you can pass it on as it is.
- **Run configs and MCP.** A `video` job in a `gather run` config or an MCP `gather.run`
  call takes `"captions": "with"`, `"skip"` or `"only"`, next to `"comments": true`. On
  MCP the job needs the `video` network grant (see [Launch grants](#launch-grants)). Add
  `"api_key_env": "GATHER_YOUTUBE_API_KEY"` to turn on the Data API fallback for that job;
  on MCP it then also needs `GATHER_AUTH_ENV_ALLOW=GATHER_YOUTUBE_API_KEY@www.googleapis.com`.

### Which path served each video

yt-dlp is the primary path for every YouTube read. Gather turns to the official YouTube
Data API v3 only when both of these hold:

1. You set your own Data API key in `GATHER_YOUTUBE_API_KEY` (or the variable you name
   with `--api-key-env`).
2. yt-dlp was throttled or failed for a reason about the path: a rate limit, a bot check,
   a timeout, a yt-dlp that would not start, or another error.

A reason about the video itself (private, removed, members-only, age-restricted,
geo-blocked, upcoming) never triggers the fallback, because the API would give the same
answer. A captions-only pass does not fall back either. The Data API serves caption text
only for videos your key's owner can edit, so the fallback returns the metadata item and
records the transcript as missing with the reason `api-no-captions`. Each fallback read
costs 1 unit of your Data API quota. `--no-api-fallback` keeps every read on yt-dlp.

The key travels only in the `X-Goog-Api-Key` request header. It never appears in a URL,
an item, a receipt or a log line.

Every item carries a route record in `meta.route`, and the `--json` catalog row shows it:

```json
{"schema": "gather.route/1", "channel": "youtube", "path": "yt-dlp", "auth": "absent",
 "elapsed_s": 8.828, "requests": 2, "bytes": 95729, "bytes_per_s": 10843.8,
 "requests_per_min": 13.59}
```

`elapsed_s`, `requests` and `bytes` cover the calls that served the item. A fallback item
has `"path": "youtube-data-api"`, `"auth": "present"`, the quota units it used, and a
`fallback_reason` that names the yt-dlp failure.

### Throttle check

`gather video-probe` reads three fixed public videos through yt-dlp, one at a time, with
at least 2 seconds between them, and reports how fast the path answered:

```bash
gather video-probe            # a verdict line and one line per video
gather video-probe --json     # the full report
```

For each video it records the metadata call's seconds and the caption download's seconds,
bytes and bytes per second. The verdict is `throttled` when any call met a rate limit or a
bot check, or when the median metadata call took longer than 20 seconds; `failing` when no
probe video could be read for another reason; and `ok` otherwise. The exit status is 0 for
`ok` and 1 for the others. The probe sends at most two requests per video and never
downloads video or audio. A run on 2026-10-03 measured a median metadata call of 6.5
seconds (9.2 calls per minute) and caption downloads of 3.7 to 3.9 seconds each, with the
verdict `ok`.

Exit codes for `gather channel`: `0` when every pending entry was attempted; `1` when
the pass ledger cannot be read, listing failed, or the pass stopped on throttling or a bot
check; `2` on bad options, including a `--timeout` of 0 or less and a negative sleep.

## Reddit

`gather reddit` reads Reddit through its official Data API with your own app. Create a
"script" app at https://www.reddit.com/prefs/apps, then set its id and secret in the
environment:

```bash
export REDDIT_CLIENT_ID=...          # the app id under the app name
export REDDIT_CLIENT_SECRET=...      # the app secret
export REDDIT_USERNAME=yourname      # optional; goes into the User-Agent Reddit asks for

gather reddit r/MachineLearning --limit 50 --store DIR      # the hot listing
gather reddit r/MachineLearning/top --time week             # hot, new, top, rising, controversial
gather reddit https://www.reddit.com/r/x/comments/abc123/title/ --depth 5 --comment-limit 200
```

- **What it reads.** A subreddit listing becomes one `post` item per post. A post URL (or
  `comments/ID`) becomes the post plus one `comment` item per comment, depth first. A post's
  text is its title, a blank line, and its body or link; a comment's text is its body. Each
  item's ref is the post or comment permalink, and its method is `reddit-oauth-api`. "More
  comments" stubs are not followed, because each one costs another request. Empty bodies are
  skipped.
- **Authentication.** Gather uses Reddit's application-only OAuth grant. The app secret goes
  only into the token request's Basic header, and the bearer token only into API request
  headers. Neither reaches a URL, an item, a receipt or an error message. The User-Agent
  follows Reddit's form, `python:gather-reach.<app id prefix>:<version> (by /u/<name>)`;
  `REDDIT_USER_AGENT` replaces it. Read-only: Gather never posts, comments or votes.
- **Pacing.** At most one request per second. When a response says no requests remain in the
  current window, Gather waits for the reset if it is 120 seconds away or less, and otherwise
  stops and names the reset time. A 429 gets one wait and one retry.
- **Route record.** Each item carries `meta.route` with `"channel": "reddit"`,
  `"path": "reddit-oauth-api"`, `"auth": "present"`, the seconds, requests and bytes of the
  read, and the last `x-ratelimit-remaining` value.
- **Same contract as Telos.** The environment names, User-Agent form, sorts, time windows,
  name and id checks, limits and normalised fields match the Telos reach reader, so a Reddit
  read means the same thing in both tools.
- **Run configs and MCP.** A `reddit` job takes `limit`, `time`, `depth` and
  `comment_limit`. On MCP it needs the `reddit` network grant and
  `GATHER_AUTH_ENV_ALLOW=REDDIT_CLIENT_ID@www.reddit.com,REDDIT_CLIENT_SECRET@www.reddit.com`.
- **Terms.** Reddit's free Data API tier covers personal and non-commercial use. Commercial
  use needs an agreement with Reddit.
## Cited reports from a local model

`gather report` turns a question and a fixed set of excerpts into a short cited report, written
by a model you run on your own machine, and checks every citation in code:

```bash
gather report "What does Gather record for each item?" --excerpts excerpts.json --model qwen3:8b
gather report "..." --excerpts excerpts.json --model olmo2:7b --endpoint http://127.0.0.1:8080/v1 --json
gather cite-check report.txt --excerpts excerpts.json     # the check alone, on any report text
```

- **Excerpts.** A JSON list of objects with `text` and optional `title`, `id` and `ref`. They
  are numbered from 1 in the order given, and each is cut to its first 4,000 characters.
- **Local models only.** `--endpoint` takes an OpenAI-compatible chat endpoint (Ollama,
  llama.cpp's server, vLLM, LM Studio) and refuses any host that is not a loopback address, so
  a hosted API cannot write the report. The default is Ollama's `http://127.0.0.1:11434/v1`.
  The request carries no credential and bypasses any proxy. Gather records the model name the
  server reports.
- **How citations are checked.** The model is asked to quote each excerpt word for word in
  double quotes, followed by the excerpt's number: `"exact words" [2]`. For each citation the
  check compares strings after normalising quote marks, dashes, spacing and case. A citation
  is `verified` when the quote appears in the cited excerpt, `not-in-source` when it does not,
  `unknown-source` when no excerpt has that number, `too-short` when the quote has fewer than
  four words, and `unchecked` when a bracketed number has no quote before it. Sentences with no
  citation are listed. Precision is verified citations over all citations.
- **A quote on every citation.** When an answer cites an excerpt number with no quote before
  it, `gather report` asks the model again. The new request repeats the question and excerpts,
  shows the previous answer and lists the sentences at fault. It asks at most 2 more times
  (`--quote-retries N` changes that; `0` turns it off) and keeps the first answer with every
  citation quoted. When none qualifies, it keeps the last answer as written, marks its unquoted
  citations `unchecked`, and records `quote_requirement: unmet` in the item meta. Each model
  call and its seconds are in `meta.attempts`; `meta.elapsed_s` is their sum.
- **Nothing is hidden.** The report text stays exactly as the model wrote it. The check result
  (every citation with its status, the counts, the uncited sentences) is in the report item's
  `meta.citation_check` and in the `--json` output.
- **The receipt.** The report is one item with method `synthesized` and `derived_from` set to
  the excerpts' content hashes. `--store DIR` adds it to a corpus.
- **Exit status.** `gather report` and `gather cite-check` exit 0 when every citation is
  verified, 1 when any is not, and 2 on an error, so either can gate a pipeline.

What the check does not prove: that the sentence around a verified quote says what the excerpt
means. A quote can be exact while the claim around it stretches the source.

**Measured precision.** On 30 fixed questions over Gather's own docs (4 excerpts each, one of
them holding the answer), with each model served by Ollama at temperature 0, pooled citation
precision stays below 0.80 for both models measured. Every citation that is unquoted, too short
or not found in its excerpt counts as a failure.

| Gather | Model | Verified / citations | Precision | Wilson 95% interval |
|---|---|---|---|---|
| 2.2.0 | qwen3:8b | 19 / 88 | 0.216 | 0.143 to 0.313 |
| 2.2.0 | olmo2:7b | 23 / 62 | 0.371 | 0.262 to 0.495 |
| 2.3.0 (quote required) | qwen3:8b | 57 / 88 | 0.648 | 0.544 to 0.739 |
| 2.3.0 (quote required) | olmo2:7b | 36 / 114 | 0.316 | 0.238 to 0.406 |

Requiring a quote on every citation tripled the verified citations for qwen3:8b. It did not help
olmo2:7b, which answered the request for quotes with more bare citations. Read each report as a
draft to check: the status on each citation tells you which sentences to compare with the source.
## Filter ledgers

`--scope` keeps the items that mention a term and drops the rest. `--ledger DIR` records
exactly what it dropped, so a reader can see the filter's effect and a second person can
recompute it:

```bash
gather docs notes/ --scope tiling,penrose --ledger out/ledger --store corpus
gather ledger verify out/ledger          # exit 0 when every count recomputes
```

`DIR/ledger.json` (schema `gather.filter-ledger/1`) holds the filters and their parameters,
the input count and a digest over the input items' content hashes in order, one row per
dropped item (its index in the input, id, content hash and reason code), the kept and dropped
counts, and the counts by reason. Every dropped item has exactly one reason code: when several
filters run, the first one that rejects an item names the reason. `DIR/input.jsonl` holds the
input items, text included, so the counts can be recomputed without the original sources.

`gather ledger verify` rebuilds the input digest, checks each row against the input item at
its index, checks that kept plus dropped equals the input total and that the counts by reason
match the rows, and runs the scope filter again to confirm it drops the same items. An input
line whose text no longer matches its hash stops the check. A `gather run` config takes
`"ledger": "DIR"` when you run it from the command line; an MCP call cannot name one.

A ledger makes the filtering inspectable. It does not show that the filtering was fair, and a
reason code can still carry a judgment inside its label.

## Web-data engine

Each command prints a receipt as JSON.

```bash
gather caps                      # what this install can do (fast / browser)
gather extract <url|file.html>   # Markdown + a per-block provenance receipt
gather markdown <url|file.html>  # structured Markdown only
gather crawl <url> --depth 2 --max-pages 50   # a witnessed, hash-chained crawl ledger
```

Optional capability backends (core stays zero-dependency; a missing one degrades to
UNVERIFIABLE, never a fake):

```bash
pip install 'gather-engine[fast]'      # lxml, about 2x parse speed
pip install 'gather-engine[browser]'   # Playwright JS render (then: playwright install chromium)
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

## Local client packages

The optional client bundle adds a bounded read-only MCP profile with an explicit
workspace selected at launch. See [client package setup](client-plugin/README.md).
Add `--allow-origin https://example.com` to opt into GET requests from one public
HTTPS origin, or `--allow-loopback-origin http://127.0.0.1:8080` for an explicitly
selected local service. Repeat a flag to grant another origin. `gather.fetch`
accepts only `url`; tool arguments and environment variables cannot grant access.
MCPB users can enter these origins in the optional setup fields as JSON arrays.
Both fields default to `[]`; leaving either blank also grants no access.
Claude Code asks for the workspace and the same two fields when you enable the plugin.
The [example launch](examples/client-network.md) includes a request and limits.
Windows x64 MCPB and ZIP bundles include their runtime; source plugins require
Python 3.11+. The full CLI/MCP retains advanced operations. Client-specific
installation and marketplace acceptance require separate verification.
