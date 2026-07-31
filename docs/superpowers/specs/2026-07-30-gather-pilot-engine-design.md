# Gather Pilot Evidence Engine

**Status:** Subproject design derived from the approved SaaS architecture;
written specification pending operator review
**Date:** 2026-07-30
**Owner:** Zentropy Labs
**Product:** Gather

## 1. Decision

This is subproject 1 of the Gather SaaS program defined in
`2026-07-30-gather-saas-master-design.md`. It delivers the portable pilot
execution and evidence layer consumed by the SaaS API and workers. Its
subproject non-goals do not constrain the complete SaaS product.

Gather's first completed pilot is a representative research-operations
showcase that turns difficult mixed sources into a continuously monitored,
operator-controlled, portable, verifiable research corpus.

The pilot is broad in demonstrated value. It covers venture and market
diligence, technical and scientific research, and media or operational
intelligence. It does not reduce Gather to one vertical.

The safety boundary is narrower than the business boundary. Live inputs must be
controlled or explicitly allowlisted. Browser-backed sources require an
additional trusted-host declaration because Gather cannot yet filter every
browser redirect and subresource request.

Gather remains a retained Zentropy Labs capability. A pilot licenses use and
delivers customer artifacts. It does not transfer Gather, its source, its
schemas, its reusable adapters, or ownership of improvements.

## 2. Customer Outcome

The customer receives an operator-controlled corpus and a report that answer:

> What material did we gather, how did each item arrive, what changed, what can
> be re-checked, what could not be verified, and which findings remain grounded
> in the captured sources?

The pilot must demonstrate three representative missions:

1. **Venture and market diligence**
   - organizations;
   - people;
   - products;
   - public claims;
   - market and product changes.
2. **Technical and scientific research**
   - papers;
   - citation relationships;
   - standards;
   - technical documentation;
   - repositories and release material.
3. **Media and operational intelligence**
   - webpages;
   - feeds;
   - transcripts;
   - PDFs;
   - local documents;
   - monitored public statements.

All three missions converge into one artifact root and one corpus. The artifact
root may live on an operator workstation, a customer-controlled host, or a
Zentropy-managed pilot host. A mission is a presentation grouping, not a
separate storage or product boundary.

## 3. Delivery Shape

The pilot adds one customer-facing command group:

```text
gather pilot run MANIFEST --output DIR
gather pilot refresh DIR
gather pilot verify DIR
gather pilot bundle DIR --output FILE --visibility shared
```

`pilot run` validates the manifest and its safety policy before any external
call. It then performs intake, persists items, verifies the corpus, performs a
monitoring pass when requested, and writes canonical JSON plus a self-contained
HTML report.

`pilot verify` runs without network access. It re-hashes the manifest snapshot,
the report payload, the corpus objects, the run records, and the monitoring
ledger. It exits nonzero if any required artifact is missing, malformed,
reordered, or modified.

`pilot refresh` first verifies an existing pilot directory. It then re-fetches
the manifest's monitored sources under the original snapshotted policy, appends
new corpus and monitoring evidence, preserves the prior report and receipt in
history, and writes a new current report and receipt. It accepts no policy or
source override on the command line.

`pilot bundle` verifies the artifact root before packaging it for transfer or
remote delivery. `--visibility shared` includes the redacted report, normalized
manifest, receipt, and public evidence needed to verify the report.
`--visibility full` additionally includes the corpus, monitoring state, history,
and private evidence and therefore requires an explicit
`--include-private-evidence` flag. Bundles are deterministic ZIP archives with a
canonical member order, fixed metadata timestamps, relative paths, and a
top-level bundle receipt.

The static HTML report and shared bundle may be hosted on an agreed remote
surface. The first pilot does not require that surface to be local, and it does
not require Gather to implement accounts, billing, or a multi-tenant service.

The repository ships two executable examples:

```text
examples/pilot/showcase-offline.json
examples/pilot/showcase-live.json
```

The offline showcase uses bundled, synthetic fixtures and performs no network
access. It must produce the same semantic result and evidence hashes on repeated
runs when given the same fixed clock. The live showcase uses public, explicitly
allowlisted sources and may produce different content hashes as those sources
change.

## 4. Pilot Manifest

The manifest schema is `gather.pilot-manifest/1`.

Required top-level fields:

```json
{
  "schema": "gather.pilot-manifest/1",
  "pilot_id": "zentropy-representative-showcase",
  "title": "Gather representative research operations pilot",
  "mode": "offline",
  "deployment": {
    "mode": "workstation",
    "custodian": "customer"
  },
  "policy": {},
  "missions": []
}
```

The closed deployment shape has:

- `mode`: exactly `workstation`, `customer_hosted`, or `zentropy_managed`;
- `custodian`: exactly `customer`, `zentropy`, or `shared`.

Deployment metadata records where the pilot ran and who controls the artifact
root. It grants no storage access and contains no hostname, credential, account
identifier, or private infrastructure path.

### 4.1 Policy

The closed policy shape is:

```json
{
  "allowed_hosts": ["example.com"],
  "trusted_browser_hosts": [],
  "allowed_local_roots": ["./fixtures"],
  "enabled_adapters": ["docs", "web", "feed", "pdf"],
  "credentials": ["GATHER_DEMO_API_TOKEN"],
  "report_private_content": false
}
```

Rules:

- Unknown policy fields are rejected.
- Host names are lowercase DNS names without a scheme, path, wildcard, user
  information, port, or trailing dot.
- A subdomain is not allowed merely because its parent is allowed. Every host
  used by the pilot must appear exactly.
- `trusted_browser_hosts` must be a subset of `allowed_hosts`.
- `allowed_local_roots` are resolved before use. A local target must remain
  inside one resolved root after symlink and `..` resolution.
- `enabled_adapters` is a subset of the adapter registry shipped by the
  installed Gather version.
- `credentials` contains environment-variable names only. Values are never
  copied into a normalized manifest, receipt, report, log, or command line.
- `report_private_content` defaults to `false`.
- Offline mode rejects every network-backed source that lacks a valid replay
  fixture before execution.
- Browser sources require both an exact `allowed_hosts` match and an exact
  `trusted_browser_hosts` match.

### 4.2 Missions and sources

Each mission has:

```json
{
  "id": "technical-research",
  "title": "Technical and scientific research",
  "sources": []
}
```

Mission IDs are unique lowercase slugs. A mission must contain at least one
source.

Each source has:

```json
{
  "id": "example-article",
  "adapter": "web",
  "target": "https://example.com/article",
  "fixture": null,
  "refresh_fixture": null,
  "visibility": "public",
  "monitor": true,
  "required": true,
  "extraction": null,
  "options": {}
}
```

Rules:

- Source IDs are unique across the whole manifest.
- `visibility` is exactly `public` or `private`.
- `monitor` is valid only for direct HTTP or HTTPS targets supported by
  Gather's accountable fetch path.
- `fixture` is either `null` or a relative path beneath an allowed local root.
- `refresh_fixture` is either `null` or a relative path beneath an allowed
  local root. It is allowed only in offline mode when `monitor` is true.
- `extraction` is either `null` or a closed deterministic field-extraction
  schema. It is supported only for `web` and `browser`.
- Offline mode requires a fixture for every normally network-backed adapter.
  The adapter parses the fixture through its existing pure parser and never
  opens a socket.
- An offline refresh uses `refresh_fixture` when present. Later refreshes use
  the same body and should produce `UNCHANGED`.
- Live mode rejects `fixture` so a fixture can never be substituted into a run
  that claims to be live.
- Live mode also rejects `refresh_fixture`.
- Unknown source fields and unknown adapter options are rejected.
- The first pilot supports the existing Gather adapters: `web`, `feed`,
  `docs`, `pdf`, `arxiv`, `scholar`, `video`, `api`, `browser`, `ocr`, and
  `transcribe`.
- Known provider hosts used by `arxiv` and `scholar` must also appear in
  `allowed_hosts` for live mode.
- A source may fail without erasing successful sources. The pilot records one
  closed outcome per source.

Allowed adapter options are closed:

| Adapter | Options |
|---|---|
| `web` | none |
| `feed` | none |
| `docs` | none |
| `pdf` | none |
| `arxiv` | `max_results` |
| `scholar` | `providers`, `federated`, `edges` |
| `video` | `comments`, `auto_captions` |
| `api` | `auth_env`, `items_key`, `id_key`, `title_key`, `text_key` |
| `browser` | `browser`, `no_sandbox` |
| `ocr` | `lang` |
| `transcribe` | `model` |

Fixture formats are adapter-specific:

- `web` and `browser`: UTF-8 HTML;
- `feed`: UTF-8 RSS or Atom XML;
- `arxiv`: recorded Atom XML;
- `scholar`: a JSON object keyed by provider name, containing recorded provider
  responses;
- `video`: a JSON object containing `info_json`, optional `vtt`, and optional
  recorded comments;
- `api`: recorded JSON response body;
- `docs`, `pdf`, `ocr`, and `transcribe`: the local material itself, so
  `target` already names the local path and `fixture` remains `null`.

The offline executor calls only pure parsers over fixture bytes. If an adapter
has no pure parser for its declared fixture format, manifest validation refuses
that source before execution.

An extraction schema is:

```json
{
  "fields": {
    "organization": {
      "selector": "h1.organization",
      "attr": null,
      "regex": null,
      "many": false,
      "required": true
    }
  }
}
```

Field names are unique non-empty strings. `selector` is required. `attr` and
`regex` are strings or `null`. `many` and `required` are booleans. Unknown
fields are rejected.

The pilot obtains the raw or rendered HTML once, builds the normal webpage
`Item`, and applies Gather's existing `extract_schema` to the same bytes. Each
reported field carries its source node path, source hash, value hash, status,
and verification verdict. A missing required extraction field makes that
source `ERROR`. Private source values and node paths are omitted from the
shared report, while their hashes and verification verdict remain.

## 5. Runtime Architecture

### 5.1 `gather.pilot_manifest`

Responsibilities:

- parse the manifest;
- reject unknown or malformed fields;
- normalize paths and host names;
- enforce adapter, host, local-root, browser-trust, and credential-name rules;
- emit a normalized manifest with a canonical SHA-256 digest.

This module performs no source fetch and reads no credential value.
Resolved absolute paths exist only in runtime objects. The serialized normalized
manifest retains canonical relative POSIX paths beneath the manifest directory,
so moving an artifact root does not leak or invalidate a workstation path.

Public interface:

```python
@dataclass(frozen=True, slots=True)
class PilotDeployment:
    mode: str
    custodian: str

@dataclass(frozen=True, slots=True)
class PilotManifest:
    schema: str
    pilot_id: str
    title: str
    mode: str
    deployment: PilotDeployment
    policy: PilotPolicy
    missions: tuple[PilotMission, ...]

def load_pilot_manifest(path: str | Path) -> PilotManifest: ...
def validate_pilot_manifest(data: Mapping[str, object], base_dir: Path) -> PilotManifest: ...
def manifest_payload(manifest: PilotManifest) -> dict[str, object]: ...
def manifest_digest(manifest: PilotManifest) -> str: ...
```

### 5.2 `gather.pilot`

Responsibilities:

- execute sources in manifest order;
- isolate source failures;
- convert adapter output into the existing `Item` shape;
- add successful items to one `Corpus`;
- create one source outcome per requested source;
- verify the corpus and stored run evidence;
- invoke monitoring for eligible sources;
- assemble one immutable pilot result.

The orchestrator composes existing adapters, `Corpus`, `digest`,
`monitor_pass`, and `verify_ledger`. It does not duplicate adapter internals.

Source outcomes use the closed set:

- `CAPTURED`: at least one item was received and stored;
- `EMPTY`: the adapter completed but returned no items;
- `UNAVAILABLE`: an optional adapter executable or package is not installed;
- `REFUSED`: the manifest or runtime safety policy refused the source;
- `ERROR`: the adapter failed for another reason.

Only `CAPTURED` counts as gathered evidence. Every other outcome remains visible
in the report and carries a bounded diagnostic without secret values.

Public interface:

```python
@dataclass(frozen=True, slots=True)
class SourceOutcome:
    mission_id: str
    source_id: str
    adapter: str
    visibility: str
    status: str
    item_count: int
    receipt_digests: tuple[str, ...]
    diagnostic: str

@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    source_id: str
    fields: tuple[dict[str, object], ...]
    missing_required: tuple[str, ...]
    verified: bool

@dataclass(frozen=True, slots=True)
class PilotResult:
    manifest_sha256: str
    source_outcomes: tuple[SourceOutcome, ...]
    extraction_outcomes: tuple[ExtractionOutcome, ...]
    corpus_digest: str
    corpus_verified: bool
    monitor_report: dict[str, object] | None
    monitor_verified: bool | None
    limitations: tuple[str, ...]
    does_not_prove: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PilotVerification:
    manifest_verified: bool
    report_verified: bool
    html_verified: bool
    corpus_verified: bool
    monitor_verified: bool | None
    receipt_verified: bool

    @property
    def ok(self) -> bool: ...

@dataclass(frozen=True, slots=True)
class PilotEvent:
    sequence: int
    kind: str
    mission_id: str | None
    source_id: str | None
    status: str

class PilotEventSink(Protocol):
    def emit(self, event: PilotEvent) -> None: ...

def run_pilot(
    manifest: PilotManifest,
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.time,
    event_sink: PilotEventSink | None = None,
) -> PilotResult: ...

def refresh_pilot(
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.time,
    event_sink: PilotEventSink | None = None,
) -> PilotResult: ...

def verify_pilot(output_dir: Path) -> PilotVerification: ...
```

Event kinds are closed: `source_started`, `source_completed`,
`source_failed`, `monitor_completed`, `report_written`, and `run_completed`.
Events contain no source body, credential, request header, private target, or
absolute path. The CLI uses a text event sink, MCP uses a collected JSON sink,
and SaaS workers persist the same events for server-sent delivery.

### 5.3 `gather.pilot_report`

Responsibilities:

- render canonical JSON from `PilotResult`;
- redact private source titles, targets, filesystem paths, and bodies when
  `report_private_content` is false;
- retain private source method, item count, receipt hashes, verdict, and
  mission membership;
- render a self-contained HTML view from the same JSON payload;
- bind both views to one semantic report digest.

The HTML contains no remote script, font, stylesheet, image, analytics, or
network request. All dynamic values are HTML-escaped.

The report schema is `gather.pilot-report/1`. It includes:

- pilot identity and mode;
- deployment mode and artifact custodian;
- Gather version;
- normalized manifest digest;
- mission summaries;
- source outcomes;
- adapter capability matrix;
- corpus item, method, kind, and visibility counts;
- corpus digest and verification verdict;
- monitoring counts, changes, failures, ledger root, and verification verdict;
- refresh sequence and history count;
- grounded extraction summaries when a source emitted them;
- limitations;
- `does_not_prove`;
- report digest.

The semantic report digest is SHA-256 over canonical JSON before the
`report_digest` field is inserted. Verification removes that field, recomputes
the digest, and compares it with the stored value.

The report does not claim:

- completeness of the public web;
- truth of captured source claims;
- correctness of machine transcription or OCR;
- availability of a source that was not captured;
- security of unrestricted browser navigation;
- product-market fit or willingness to pay.

### 5.4 `gather.pilot_bundle`

Responsibilities:

- verify the source artifact root before reading files;
- select the closed `shared` or `full` member set;
- refuse private material in a shared bundle;
- create a deterministic ZIP archive;
- add `bundle-receipt.json` with each member's relative path and SHA-256;
- verify the completed archive before returning success.

The shared bundle never includes corpus objects, private source refs, private
extraction values, monitoring request headers, credentials, or local absolute
paths. It refuses a pilot whose `report_private_content` policy is true. Its
`manifest-digest.json` contains the manifest schema, pilot ID, manifest digest,
deployment metadata, mission IDs, source IDs, adapters, visibility labels, and
outcomes, but no source targets, local roots, browser hosts, or credential
names. The full bundle is an explicit custody transfer artifact, not a public
share artifact.

Public interface:

```python
@dataclass(frozen=True, slots=True)
class PilotBundleReceipt:
    schema: str
    visibility: str
    source_receipt_sha256: str
    members: tuple[tuple[str, str], ...]
    bundle_digest: str

def bundle_pilot(
    output_dir: Path,
    bundle_path: Path,
    *,
    visibility: str,
    include_private_evidence: bool = False,
) -> PilotBundleReceipt: ...

def verify_pilot_bundle(bundle_path: Path) -> bool: ...
```

### 5.5 CLI and MCP

The CLI exposes `pilot run`, `pilot refresh`, `pilot verify`, and `pilot
bundle`.

The MCP server adds one read/write-local-filesystem tool:

```text
gather.pilot
```

Inputs:

- `action`: exactly `run`, `refresh`, `verify`, or `bundle`;
- `manifest`: inline object or local manifest path, required only for `run`;
- `output`: required artifact root;
- `bundle_output`: required only for `bundle`;
- `visibility`: `shared` or `full`, required only for `bundle`;
- `include_private_evidence`: explicit boolean confirmation for a full bundle.

The MCP tool runs the same manifest validator and orchestrator as the CLI. It
does not accept policy overrides outside the manifest. It returns the report
payload, artifact paths, and verification verdict. `refresh` and `verify`
accept no manifest because the normalized snapshot inside `output` is
authoritative. `bundle` accepts no manifest and packages only a verified
artifact root.

`gather.status` advertises the pilot command and MCP tool. `gather.doctor`
reports whether optional adapters requested by a manifest are available only
when the pilot command performs a manifest-specific preflight. The general
doctor command remains dependency-light.

## 6. Data Flow

1. Read the manifest.
2. Resolve its directory and normalize all local roots and source targets.
3. Validate the complete closed schema.
4. Check every network source against `allowed_hosts`.
5. Check every browser source against `trusted_browser_hosts`.
6. Check every local source against `allowed_local_roots`.
7. In offline mode, resolve every network-backed source to its declared local
   replay fixture and install a transport that cannot open a socket.
8. Snapshot the normalized manifest without credential values.
9. Execute each source independently in manifest order.
10. Apply and verify any declared deterministic field extraction against the
    same captured HTML.
11. Store every successful item in one content-addressed corpus.
12. Record one `SourceOutcome` for every source, including failures.
13. Verify corpus objects and run records.
14. Run one accountable monitoring pass for eligible sources.
15. Verify the monitoring ledger.
16. Write the canonical JSON report.
17. Render HTML from that JSON payload.
18. Write a pilot receipt that binds the manifest, report, corpus digest, and
    monitoring root.
19. Re-open the artifacts and run `verify_pilot` before returning success.

A refresh follows this additional sequence:

1. Verify the complete existing pilot directory.
2. Load only `manifest.normalized.json`; accept no replacement manifest.
3. Re-run monitored sources under the snapshotted policy.
4. Append new items and run records to the existing corpus.
5. Append monitoring observations to the existing hash chain.
6. Move the prior JSON report, HTML report, and receipt into the next
   zero-padded `history/NNNN/` directory.
7. Write the new current report and receipt through temporary sibling files,
   then replace the current files only after their digests verify.
8. Re-open the complete directory and run `verify_pilot`.

A bundle follows this additional sequence:

1. Verify the complete source artifact root.
2. Select the closed member set for `shared` or `full`.
3. Scan member paths and payloads for absolute local paths and credential-shaped
   values.
4. Build `bundle-receipt.json` over canonical relative paths and member hashes.
5. Write a deterministic ZIP to a temporary sibling path using lexicographic
   member order, `1980-01-01T00:00:00` ZIP timestamps, and normalized POSIX
   member paths.
6. Re-open the ZIP, verify every member and the bundle receipt, then atomically
   replace the requested bundle path.

If validation fails, no output directory is created and no source executes.
If execution partially fails, successful evidence is preserved and the command
exits nonzero after writing a truthful partial report. A fully offline showcase
must exit zero.

## 7. Output Contract

The output directory is:

```text
DIR/
  manifest.normalized.json
  corpus/
    objects/
    catalog.jsonl
    runs.jsonl
  monitor-state.json
  pilot-report.json
  pilot-report.html
  pilot-receipt.json
  history/
    0001/
      pilot-report.json
      pilot-report.html
      pilot-receipt.json
```

`monitor-state.json` is present only when the manifest requests monitoring.

`pilot run` refuses a non-empty destination. `pilot refresh` is the only
operation allowed to replace current report files, and it first preserves their
verified prior versions in append-only numbered history. The operator may also
choose a new output directory.

`pilot-receipt.json` uses schema `gather.pilot-receipt/1` and binds:

- normalized manifest SHA-256;
- JSON report SHA-256;
- HTML report SHA-256;
- semantic report digest;
- corpus digest;
- monitor root hash when present;
- history count and a hash-chain root over archived receipt SHA-256 values;
- Gather version;
- artifact relative paths.

All artifact paths in shareable payloads are relative to the pilot output
directory.

The artifact root is deployment-neutral. It may be created on a workstation,
inside a customer-controlled VM or container, or inside an agreed
Zentropy-managed environment. A bundle may be transferred or hosted through a
separate approved delivery surface without changing its receipts. Gather
records the declared deployment mode but does not claim the surrounding host's
encryption, identity, retention, backup, or access-control posture.

## 8. Representative Showcase

The bundled showcase must exercise representative value without relying on
private or copyrighted third-party material.

### 8.1 Offline showcase

Original synthetic fixtures represent:

- a venture studio portfolio page and founder profile;
- a technical project release note and documentation page;
- a small scholarly metadata response with a citation edge;
- a newsroom feed and transcript excerpt;
- a local private memo represented in the shared report only by method, count,
  and hashes;
- a changed second version of one monitored source.

The offline run demonstrates:

- replay through the web, feed, scholarly, video, and API parsers;
- direct local document intake;
- public and private visibility;
- corpus deduplication;
- per-item receipts;
- grounded structured extraction;
- a monitoring change produced by recorded version-one and version-two fixture
  bodies;
- a verified monitor ledger;
- report redaction;
- tamper detection.

The fixtures are original repository content and contain no real personal
information, customer data, or copied article bodies.

### 8.2 Live showcase

The live manifest is a template, not a promise that external sources remain
available. It contains no credential and identifies every required host. It
demonstrates public web, feed, arXiv or scholarly federation, and monitoring.

External failures become typed source outcomes. They never get replaced by
offline fixture results inside a run that claims to be live.

## 9. Inputs for the PSL and Reusable Partner Packages

This subproject produces verified content inputs for two later delivery
packages. Subproject 4 of the SaaS master design owns the pitch, commercial
copy, pricing presentation, and final package assembly.

1. **PSL package**
   - connects Gather to PSL's ideation, diligence, market mapping, technical
     research, and portfolio-monitoring work;
   - shows how one corpus supports both studio validation and fund diligence;
   - extends the existing Zentropy Labs deck and five-minute verification demo;
   - states that Gather remains a Zentropy Labs retained capability.
2. **Reusable partner package**
   - describes the same pilot without PSL-specific claims;
   - maps the three missions to venture studios, research organizations,
     newsrooms, engineering teams, and regulated operators;
   - includes the operator runbook, manifest template, sample report, safety
     boundary, and commercial boundary.
   - offers workstation, customer-hosted, and Zentropy-managed pilot delivery;
   - includes a verified shared bundle suitable for remote review.

The engine does not generate negotiation language. Its sample reports,
receipts, capability matrix, and demonstrations remain factual inputs. Later
packages may describe pilots, licensing, services, collaboration, and advisory
relationships, but must not describe Gather as available for sale or
acquisition.

## 10. Commercial Boundary

The public repository's existing fair-source license remains unchanged.

The pilot package states:

- Gather and all reusable product code remain owned by Zentropy Labs.
- The customer owns material it supplies.
- The customer receives its corpus, reports, and agreed customer-specific
  configuration.
- Deployment may be workstation-based, customer-hosted, or Zentropy-managed.
- Remote operation and delivery require an explicit custody agreement covering
  access, retention, deletion, and incident responsibility.
- No exclusivity, assignment, source transfer, acquisition option, or ownership
  of general improvements is implied.
- Any production or commercial deployment requires terms consistent with
  Gather's existing license.

The package may include an illustrative capped services pilot derived from the
existing Zentropy economics brief. It must label pricing as proposed until the
operator publishes or sends it. This implementation does not send outreach,
accept payment, or bind either party to legal terms.

## 11. Documentation

The repository adds:

- `docs/PILOT.md`: customer-facing purpose, outcome, boundaries, run commands,
  artifact guide, and retained-capability statement;
- `examples/pilot/README.md`: offline and live demonstration runbook;
- `examples/pilot/showcase-offline.json`;
- `examples/pilot/showcase-live.json`;
- original synthetic fixtures;
- one checked-in redacted sample report;
- one checked-in shared bundle receipt and a documented bundle command;
- README and USAGE links to the pilot.

The PSL-specific narrative remains in the private `project-docs` outreach
repository. The public Gather repository contains no negotiation notes,
personal dossiers, private contact data, or unpublished customer material.

## 12. Error Handling

- Manifest errors use `REFUSED` language and exit code `2`.
- Runtime source failures produce typed source outcomes and a partial report.
- A run with any required source outside `CAPTURED` exits code `1`.
- Optional sources may fail without making the overall result fail, but remain
  visible.
- Artifact verification failure exits code `1`.
- Bundle verification failure exits code `1` and leaves no final bundle.
- `pilot run` refuses an existing non-empty output directory before any source
  runs.
- `pilot refresh` refuses an invalid existing pilot directory before any source
  runs or current artifact changes.
- A missing optional executable is `UNAVAILABLE`, not `ERROR`.
- Diagnostics are bounded to 240 characters and remove credential values.
- Exceptions never cause a failed source to disappear from the report.

Each source therefore adds:

```json
{
  "required": true
}
```

`required` defaults to `true`.

## 13. Testing

### Unit tests

- closed manifest schemas reject unknown fields;
- hosts require exact allowlist membership;
- browser hosts require the trusted subset;
- offline mode refuses a network-backed adapter without a valid fixture;
- local targets cannot escape allowed roots through `..` or symlinks;
- credential names validate without reading their values;
- offline network-backed adapters require valid replay fixtures;
- live mode refuses replay fixtures;
- an offline executor cannot open a socket;
- refresh fixtures are offline-only and require monitoring;
- extraction schemas reject unknown fields and unsupported adapters;
- required extraction fields must be present and re-verifiable;
- source failures become the correct closed outcome;
- optional failures do not erase successful evidence;
- redaction removes private target, title, path, and body values;
- HTML escaping prevents markup injection;
- report and receipt digests change when bound content changes;
- output paths are relative;
- non-empty destinations are refused.
- shared bundles exclude private evidence even when the source artifact root
  contains it;
- full bundles require explicit private-evidence confirmation;
- bundle paths and timestamps are deterministic;
- tampering with a bundled member breaks bundle verification;

### Integration tests

- the offline showcase runs without network access;
- repeated offline runs under the fixed test clock have identical semantic
  payloads and digests;
- the corpus verifies;
- the monitoring ledger verifies;
- changing the monitored fixture produces `CHANGED`;
- a second offline refresh over the same refresh fixture produces `UNCHANGED`;
- refresh refuses an invalid existing receipt before any external call;
- refresh preserves prior reports and receipts in numbered history;
- tampering with a corpus object, report, manifest snapshot, receipt, or
  monitoring entry makes `gather pilot verify` fail;
- CLI and MCP produce the same report schema and verification verdict;
- a required failed source writes a partial report and returns nonzero;
- no pilot execution path invokes unrestricted network behavior in offline
  mode.

### Repository gates

```text
python -m pytest
python -m ruff check src tests examples
python -m mypy src
gather status --json
gather doctor --json
gather pilot run examples/pilot/showcase-offline.json --output <empty-dir>
gather pilot bundle <pilot-dir> --output <bundle.zip> --visibility shared
gather pilot verify <output-dir>
```

## 14. Acceptance Criteria

The pilot is complete only when:

1. One CLI command produces the complete offline artifact set.
2. One refresh command produces a `CHANGED` observation and preserves the
   initial report in history.
3. The offline run exercises all three missions.
4. Report integration tests exercise successful, unavailable, and changed
   outcomes without converting any failure into success.
5. The corpus, monitoring ledger, and history chain independently verify.
6. The shared report redacts private material while retaining useful proof.
7. CLI and MCP use the same implementation.
8. The HTML report is self-contained and opens without a server.
9. `pilot verify` catches deliberate tampering and exits nonzero.
10. The full test, lint, and type-check gates pass.
11. The public docs state the retained Zentropy ownership boundary.
12. The checked-in sample report and capability matrix provide verified inputs
    for the later PSL and reusable partner packages.
13. A verified shared bundle can be delivered or hosted remotely without
    exposing private evidence.

## 15. Non-Goals

The first pilot does not:

- build a multi-tenant hosted SaaS;
- add billing, accounts, or vendor-specific cloud-storage SDKs;
- crawl unrestricted customer-provided domains;
- claim that captured statements are true;
- make browser navigation safe for hostile arbitrary URLs;
- replace Gather's adapters with a new abstraction;
- require an LLM;
- promise complete market, scholarly, or media coverage;
- transfer or offer Gather for acquisition;
- send an email or contact a partner.

## 16. Does Not Prove

A completed pilot does not by itself prove:

- product-market fit;
- customer willingness to pay;
- comprehensive source coverage;
- legal sufficiency for regulated retention;
- truth of source claims;
- correctness of OCR, transcription, or external metadata;
- safety of unrestricted browser automation;
- that PSL or another organization will partner, invest, advise, or purchase.

Those require customer use, independent review, and commercial conversations.
