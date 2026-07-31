# Gather Pilot Evidence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a portable `gather pilot` evidence engine that runs the approved representative offline and controlled-live pilots, preserves partial source outcomes, produces independently verifiable reports and bundles, and exposes the same behavior through Python, CLI, and MCP.

**Architecture:** Add a thin pilot layer over Gather's existing pure parsers, `Corpus`, schema extraction, digest, monitoring, CLI, and MCP surfaces. The layer validates one closed manifest before I/O, executes each source independently, writes immutable evidence plus current report views, verifies every binding offline, and packages a redacted or full deterministic ZIP. This plan implements subproject 1 only; the FastAPI control plane, React application, billing, and deployment system remain in later approved subprojects.

**Tech Stack:** Python 3.11 standard library, Gather's zero-dependency engine, `dataclasses`, `pathlib`, `argparse`, `zipfile`, `html`, `hashlib`, JSON, pytest, Ruff, mypy.

## Global Constraints

- Follow `AGENTS.md`: keep Python, CLI, and MCP aligned; prefer receipts and verdicts over raw private material; update public docs and examples.
- Follow the approved specifications:
  - `docs/superpowers/specs/2026-07-30-gather-saas-master-design.md`
  - `docs/superpowers/specs/2026-07-30-gather-pilot-engine-design.md`
- Preserve the zero-required-dependency core.
- Do not add a new network transport. Live execution composes existing source classes.
- No production deployment, outreach, billing activation, or partner-specific commercial copy is part of this plan.
- Every production change starts with a test that fails for the intended reason.
- Use fixed clocks in receipt, report, monitor, and bundle tests.
- Keep diagnostics at 240 characters or fewer and scrub credential values.
- Never serialize absolute paths, credential values, request headers, or private source bodies into shared artifacts or events.
- Use canonical JSON as `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
- Commit after every task. Before each commit, run the task's focused tests and `python -m ruff check` on touched Python files.

---

## Task 1: Closed Pilot Manifest and Safety Policy

**Files:**

- Create: `src/gather/pilot_manifest.py`
- Create: `tests/test_pilot_manifest.py`

### Contract to implement

The module owns immutable manifest runtime types, closed-key validation, normalized serialization, and the manifest digest. It performs no fetch and reads no credential values.

```python
ADAPTERS = (
    "web", "feed", "docs", "pdf", "arxiv", "scholar",
    "video", "api", "browser", "ocr", "transcribe",
)
NETWORK_ADAPTERS = ("web", "feed", "arxiv", "scholar", "video", "api", "browser")
MONITOR_ADAPTERS = ("web", "feed", "api")
PILOT_MANIFEST_SCHEMA = "gather.pilot-manifest/1"

@dataclass(frozen=True, slots=True)
class PilotDeployment:
    mode: str
    custodian: str

@dataclass(frozen=True, slots=True)
class PilotPolicy:
    allowed_hosts: tuple[str, ...]
    trusted_browser_hosts: tuple[str, ...]
    allowed_local_roots: tuple[str, ...]
    enabled_adapters: tuple[str, ...]
    credentials: tuple[str, ...]
    report_private_content: bool

@dataclass(frozen=True, slots=True)
class PilotSource:
    id: str
    adapter: str
    target: str
    fixture: str | None
    refresh_fixture: str | None
    visibility: str
    monitor: bool
    required: bool
    extraction: Mapping[str, Field] | None
    options: Mapping[str, object]
    resolved_target: Path | None
    resolved_fixture: Path | None
    resolved_refresh_fixture: Path | None

@dataclass(frozen=True, slots=True)
class PilotMission:
    id: str
    title: str
    sources: tuple[PilotSource, ...]

@dataclass(frozen=True, slots=True)
class PilotManifest:
    schema: str
    pilot_id: str
    title: str
    mode: str
    deployment: PilotDeployment
    policy: PilotPolicy
    missions: tuple[PilotMission, ...]
    base_dir: Path
```

- [ ] **Step 1: Write the closed-schema and canonicalization tests**

Add tests covering a valid minimum offline docs manifest, unknown keys at every level, duplicate mission/source IDs, invalid slugs, invalid deployment values, invalid visibility, invalid option keys, unsupported extraction, invalid credential names, and deterministic digest.

```python
def test_manifest_digest_is_independent_of_input_key_order(tmp_path):
    first = valid_manifest(tmp_path)
    second = json.loads(json.dumps(first))
    second["policy"] = dict(reversed(list(second["policy"].items())))

    one = validate_pilot_manifest(first, tmp_path)
    two = validate_pilot_manifest(second, tmp_path)

    assert manifest_payload(one) == manifest_payload(two)
    assert manifest_digest(one) == manifest_digest(two)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update({"surprise": True}), "unknown manifest field"),
        (lambda d: d["policy"].update({"wildcard": "*"}), "unknown policy field"),
        (lambda d: d["missions"][0]["sources"][0].update({"retry": 9}), "unknown source field"),
    ],
)
def test_closed_shapes_refuse_unknown_fields(tmp_path, mutate, message):
    data = valid_manifest(tmp_path)
    mutate(data)
    with pytest.raises(ValueError, match=message):
        validate_pilot_manifest(data, tmp_path)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_manifest.py -q
```

Expected: collection fails because `gather.pilot_manifest` does not exist.

- [ ] **Step 3: Implement immutable shapes, type readers, and closed-key helpers**

Implement helpers with located errors rather than implicit coercion:

```python
def _closed(data: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} field: {unknown[0]}")


def _string(data: Mapping[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value
```

Do not use `str(value)`, `bool(value)`, or permissive list conversion on untrusted manifest fields.

- [ ] **Step 4: Implement host, path, adapter, option, and extraction validation**

Use `urllib.parse.urlsplit` and exact host membership. Reject wildcard, port, userinfo, IP-literal shortcuts, trailing dot, mixed case, and implicit subdomain matches.

```python
def _network_host(target: str) -> str:
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("network target must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("network target may not contain user information or a port")
    return parsed.hostname.lower()


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve(strict=True)
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)
```

Known provider host checks:

```python
PROVIDER_HOSTS = {
    "arxiv": ("export.arxiv.org",),
    "scholar": (
        "api.openalex.org",
        "api.semanticscholar.org",
        "api.crossref.org",
    ),
}
```

Validate each adapter against this closed option map:

```python
ADAPTER_OPTIONS = {
    "web": frozenset(),
    "feed": frozenset(),
    "docs": frozenset(),
    "pdf": frozenset(),
    "arxiv": frozenset({"max_results"}),
    "scholar": frozenset({"providers", "federated", "edges"}),
    "video": frozenset({"comments", "auto_captions"}),
    "api": frozenset({"auth_env", "items_key", "id_key", "title_key", "text_key"}),
    "browser": frozenset({"browser", "no_sandbox"}),
    "ocr": frozenset({"lang"}),
    "transcribe": frozenset({"model"}),
}
```

- [ ] **Step 5: Implement normalized payload and digest**

Runtime-only `base_dir` and resolved paths must not appear in the payload. Normalize tuple order where order has no meaning, preserve mission/source order where it does, and serialize relative paths with `Path.as_posix()`.

```python
def manifest_digest(manifest: PilotManifest) -> str:
    raw = json.dumps(
        manifest_payload(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 6: Add path-escape and mode-boundary tests**

Cover `..`, a symlink escaping the allowlisted root, offline network source without fixture, live source with fixture, refresh fixture without monitor, browser host not trusted, exact host mismatch, and credential values never read.

Patch `os.environ` with a sentinel secret and assert it never appears in the normalized payload or exception strings.

- [ ] **Step 7: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot_manifest.py -q
python -m ruff check src/gather/pilot_manifest.py tests/test_pilot_manifest.py
python -m mypy src/gather/pilot_manifest.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```text
git add src/gather/pilot_manifest.py tests/test_pilot_manifest.py
git commit -m "feat: validate closed pilot manifests"
```

---

## Task 2: Pure Fixture Replay Registry

**Files:**

- Create: `src/gather/pilot_sources.py`
- Create: `tests/test_pilot_sources.py`

### Contract to implement

The registry has one entry per approved adapter. Offline replay calls existing pure parsers only. Live execution constructs existing `Source` implementations only.

```python
class AdapterUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapturedSource:
    items: tuple[Item, ...]
    extra_receipts: tuple[dict[str, object], ...] = ()
    extraction_html: str | None = None


def capture_source(
    source: PilotSource,
    manifest: PilotManifest,
    *,
    clock: Callable[[], float],
    refresh: bool = False,
) -> CapturedSource: ...
```

- [ ] **Step 1: Write replay tests for every network-backed adapter**

Use small original fixture strings in the test module and exercise:

- `web` via `parse_web`;
- `feed` via `parse_feed`;
- `arxiv` via `parse_arxiv`;
- `scholar` via provider-keyed JSON, provider parser, `work_to_item`, optional `federate`, and optional citation-edge items;
- `video` via `parse_video`;
- `api` via `parse_api`;
- `browser` via `parse_browser`.

Assert source, method, ref, item count, and content hash, not only text.

- [ ] **Step 2: Add the no-network invariant test**

```python
def test_offline_replay_never_opens_a_socket(tmp_path, monkeypatch):
    manifest = load_fixture_manifest(tmp_path, adapter="web")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline replay opened a socket")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = capture_source(
        manifest.missions[0].sources[0],
        manifest,
        clock=lambda: 1700000000.0,
    )
    assert len(result.items) == 1
```

- [ ] **Step 3: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_sources.py -q
```

Expected: collection fails because `gather.pilot_sources` does not exist.

- [ ] **Step 4: Implement fixture replay functions**

Use a closed dispatch dictionary and explicit adapter functions:

```python
ReplayFn = Callable[[PilotSource, Path, float], CapturedSource]

REPLAYERS: dict[str, ReplayFn] = {
    "web": _replay_web,
    "feed": _replay_feed,
    "arxiv": _replay_arxiv,
    "scholar": _replay_scholar,
    "video": _replay_video,
    "api": _replay_api,
    "browser": _replay_browser,
}
```

For Scholar, reuse `ScholarSource.graph` with an injected fixture fetcher. This
keeps the existing provider parsing, federation, item conversion, and citation
receipt shapes:

```python
def _replay_scholar(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    selected = tuple(source.options.get("providers", PROVIDERS))

    def fixture_fetcher(provider: str, _url: str) -> str:
        if provider not in payload:
            raise ValueError(f"scholar fixture missing provider {provider!r}")
        return json.dumps(payload[provider], ensure_ascii=False, sort_keys=True)

    adapter = ScholarSource(
        providers=selected,
        federated=bool(source.options.get("federated", True)),
        fetcher=fixture_fetcher,
        clock=lambda: at,
    )
    if bool(source.options.get("edges", False)):
        items, edges = adapter.graph(source.target)
        return CapturedSource(tuple(items), tuple(edges))
    return CapturedSource(tuple(adapter.fetch(source.target)))
```

`extra_receipts` are receipt-only graph edges. They are folded with item
receipts through `digest_of_receipts` in the per-source run evidence and source
outcome. They are not passed to `Corpus.add`, because the existing corpus stores
`Item` bodies and Scholar already defines citation edges as receipt-only
evidence.

- [ ] **Step 5: Implement direct local and live dispatch**

Local adapters call the existing source classes:

```python
LOCAL_FACTORIES = {
    "docs": lambda options: DocsSource(),
    "pdf": lambda options: PdfSource(),
    "ocr": lambda options: OcrSource(lang=options.get("lang", "eng")),
    "transcribe": lambda options: TranscribeSource(model=options.get("model", "base")),
}
```

Live factories must construct current adapters with only manifest-approved options. Catch missing executables or modules at the pilot orchestrator boundary as `AdapterUnavailable`; do not turn network/runtime errors into unavailable.

- [ ] **Step 6: Add refresh-fixture selection and HTML extraction preservation**

An offline initial run uses `fixture`; a refresh uses `refresh_fixture` when present and otherwise reuses `fixture`. Web and browser replay return the exact HTML in `extraction_html`.

- [ ] **Step 7: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot_sources.py -q
python -m ruff check src/gather/pilot_sources.py tests/test_pilot_sources.py
python -m mypy src/gather/pilot_sources.py
```

- [ ] **Step 8: Commit**

```text
git add src/gather/pilot_sources.py tests/test_pilot_sources.py
git commit -m "feat: replay pilot sources through pure adapters"
```

---

## Task 3: Source-Isolated Pilot Orchestrator

**Files:**

- Create: `src/gather/pilot.py`
- Create: `tests/test_pilot.py`

### Contract to implement

The orchestrator runs sources in manifest order, persists successful items to one `Corpus`, records exactly one outcome per requested source, never erases partial success, emits bounded safe events, and returns an immutable result.

- [ ] **Step 1: Write result, event, and source-isolation tests**

```python
def test_source_failure_does_not_erase_success(tmp_path, monkeypatch):
    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([
        CapturedSource((sample_item("kept"),)),
        RuntimeError("upstream refused"),
    ])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))
    events = CollectingSink()

    result = run_pilot(
        manifest,
        tmp_path / "out",
        clock=lambda: 1700000000.0,
        event_sink=events,
    )

    assert [o.status for o in result.source_outcomes] == ["CAPTURED", "ERROR"]
    assert Corpus(str(tmp_path / "out" / "corpus")).stats()["items"] == 1
    assert [e.sequence for e in events.events] == list(range(1, len(events.events) + 1))
    assert all("upstream" not in json.dumps(asdict(e)) for e in events.events)
```

Also test `EMPTY`, `UNAVAILABLE`, `REFUSED`, required failure, receipt digest identity, extraction missing required, output directory refusal, and a diagnostic containing a credential value.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot.py -q
```

- [ ] **Step 3: Implement public dataclasses and serialization**

Use the exact approved interfaces for:

- `SourceOutcome`;
- `ExtractionOutcome`;
- `PilotResult`;
- `PilotVerification`;
- `PilotEvent`;
- `PilotEventSink`.

Add `to_dict()` methods that preserve closed field names. `PilotVerification.ok` is true only when every required boolean is true and `monitor_verified` is either true or `None`.

- [ ] **Step 4: Implement safe diagnostics and event emission**

```python
def _diagnostic(exc: BaseException, credential_names: tuple[str, ...]) -> str:
    text = " ".join(str(exc).split())
    for name in credential_names:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text[:240]
```

Events contain only sequence, closed kind, mission/source IDs, and status. Do not put target, diagnostic, path, or counts in an event.

- [ ] **Step 5: Implement one-source execution**

For each source:

1. emit `source_started`;
2. call `capture_source`;
3. run schema extraction on preserved HTML when configured;
4. make a missing required extraction an `ERROR`;
5. add captured items as one `Corpus.add` batch;
6. combine per-item receipt rows with `CapturedSource.extra_receipts`, seal them
   with `digest_of_receipts`, and expose their individual canonical hashes in
   the source outcome;
7. append a witnessed per-source run record to `Corpus.runs.jsonl`;
8. emit `source_completed` or `source_failed`.

Classify:

```python
except AdapterUnavailable as exc:
    status = "UNAVAILABLE"
except PilotRefusal as exc:
    status = "REFUSED"
except Exception as exc:
    status = "ERROR"
```

- [ ] **Step 6: Implement output-root initialization and manifest snapshot**

Refuse any existing non-empty directory. Create:

```text
manifest.json
corpus/
monitor-state.json
history/
```

Write the normalized manifest atomically using a sibling `.tmp` file and `os.replace`. Never serialize runtime resolved paths.

- [ ] **Step 7: Implement corpus and run verification helpers**

Corpus verification requires every `Corpus.verify()` row to be `MATCH`. Run verification reconstructs every `RunRecord` and calls the existing `gather.run.verify_record`.

- [ ] **Step 8: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot.py -q
python -m ruff check src/gather/pilot.py tests/test_pilot.py
python -m mypy src/gather/pilot.py
```

- [ ] **Step 9: Commit**

```text
git add src/gather/pilot.py tests/test_pilot.py
git commit -m "feat: orchestrate source-isolated pilot runs"
```

---

## Task 4: Canonical Report, HTML View, Receipt, and Offline Verification

**Files:**

- Create: `src/gather/pilot_report.py`
- Create: `tests/test_pilot_report.py`
- Modify: `src/gather/pilot.py`

### Contract to implement

Current artifacts:

```text
report.json
report.html
pilot-receipt.json
```

The semantic report digest excludes its own `report_digest` field. The pilot receipt binds the manifest, JSON bytes, HTML bytes, semantic report, corpus, monitor root, history chain, Gather version, and relative artifact paths.

- [ ] **Step 1: Write canonical digest, redaction, escaping, and tamper tests**

```python
def test_shared_report_redacts_private_source_material(tmp_path):
    result, manifest = private_result(tmp_path, target="C:/clients/secret-plan.txt")
    payload = report_payload(manifest, result, corpus_stats={"items": 1})
    rendered = json.dumps(payload)

    assert "secret-plan" not in rendered
    assert "C:/clients" not in rendered
    assert payload["missions"][0]["sources"][0]["visibility"] == "private"
    assert payload["missions"][0]["sources"][0]["item_count"] == 1
    assert payload["missions"][0]["sources"][0]["receipt_digests"]


def test_html_escapes_all_dynamic_values():
    html_text = render_report_html({"title": '<img src=x onerror="alert(1)">'})
    assert "<img" not in html_text
    assert "&lt;img" in html_text
    assert "https://" not in html_text
```

Tamper each bound artifact independently and assert `verify_pilot(...).ok` becomes false.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_report.py -q
```

- [ ] **Step 3: Implement canonical JSON and atomic byte helpers**

```python
def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
```

Only canonical JSON byte output is accepted for `manifest.json`, `report.json`, and `pilot-receipt.json`.

- [ ] **Step 4: Implement report payload and redaction**

Use schema `gather.pilot-report/1`. Include:

- identity, mode, deployment, version, and manifest digest;
- mission summaries and source outcomes;
- adapter capability matrix;
- corpus stats and verification;
- monitoring counts and root when present;
- extraction receipts;
- refresh and history counts;
- limitations and `does_not_prove`;
- `report_digest`.

Private shared output retains mission ID, source ID, adapter, visibility, status, item count, receipt digests, and extraction hashes/verdicts. It omits title, target, body, local path, extraction value, and node path.

- [ ] **Step 5: Implement self-contained semantic HTML**

Render from the report payload only. Use one embedded `<style>` block, system fonts, semantic headings/tables, print rules, and verdict-only status color. Escape every value with `html.escape`. Include no script, remote URL, font, image, analytics, or fetch.

- [ ] **Step 6: Implement receipt construction and verification**

```python
PILOT_RECEIPT_SCHEMA = "gather.pilot-receipt/1"

def build_pilot_receipt(root: Path, report: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": PILOT_RECEIPT_SCHEMA,
        "manifest_sha256": sha256_bytes((root / "manifest.json").read_bytes()),
        "report_json_sha256": sha256_bytes((root / "report.json").read_bytes()),
        "report_html_sha256": sha256_bytes((root / "report.html").read_bytes()),
        "semantic_report_sha256": report["report_digest"],
        "corpus_digest": report["corpus"]["digest"],
        "monitor_root_hash": report["monitoring"].get("root_hash"),
        "history_count": report["history_count"],
        "history_root_hash": history_root(root / "history"),
        "gather_version": __version__,
        "artifacts": {
            "manifest": "manifest.json",
            "report_json": "report.json",
            "report_html": "report.html",
            "corpus": "corpus",
            "monitor_state": "monitor-state.json",
        },
    }
```

Verification must:

1. parse all JSON with located errors;
2. recompute semantic report digest after removing `report_digest`;
3. compare every byte digest in the receipt;
4. verify corpus rows and run records;
5. verify monitor ledger when present;
6. verify history chain;
7. reject absolute or escaping artifact paths.

- [ ] **Step 7: Wire report writing into `run_pilot`**

Write report JSON, then HTML, then receipt. Emit `report_written` only after all three atomic writes succeed. Emit `run_completed` last.

- [ ] **Step 8: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot.py tests/test_pilot_report.py -q
python -m ruff check src/gather/pilot.py src/gather/pilot_report.py tests/test_pilot_report.py
python -m mypy src/gather/pilot.py src/gather/pilot_report.py
```

- [ ] **Step 9: Commit**

```text
git add src/gather/pilot.py src/gather/pilot_report.py tests/test_pilot_report.py
git commit -m "feat: write and verify pilot evidence reports"
```

---

## Task 5: Monitoring Refresh and Receipt History

**Files:**

- Modify: `src/gather/pilot.py`
- Create: `tests/test_pilot_refresh.py`

### Contract to implement

Initial monitored capture produces `NEW`. The first offline refresh can use `refresh_fixture` and produce `CHANGED`. The next refresh over the same fixture produces `UNCHANGED`. A refresh verifies first, archives prior current artifacts, uses the snapshotted manifest only, appends evidence, and atomically replaces current views.

- [ ] **Step 1: Write initial, changed, unchanged, and preflight-refusal tests**

```python
def test_refresh_changes_then_stabilizes(tmp_path):
    root = tmp_path / "pilot"
    run_pilot(showcase_manifest(tmp_path), root, clock=lambda: 100.0)
    first = refresh_pilot(root, clock=lambda: 200.0)
    second = refresh_pilot(root, clock=lambda: 300.0)

    assert first.monitor_report["counts"]["CHANGED"] == 1
    assert second.monitor_report["counts"]["UNCHANGED"] == 1
    assert sorted(path.name for path in (root / "history").iterdir()) == [
        "0001-pilot-receipt.json",
        "0001-report.html",
        "0001-report.json",
        "0002-pilot-receipt.json",
        "0002-report.html",
        "0002-report.json",
    ]
```

Tamper the current receipt, patch `capture_source` to fail if called, run refresh, and assert it refuses before that call and before any current file changes.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_refresh.py -q
```

- [ ] **Step 3: Implement a monitor fetch seam over captured fixture bytes**

Compose `monitor_pass` rather than creating a new ledger. Build a lightweight receipt object carrying:

```python
@dataclass(frozen=True, slots=True)
class PilotFetchReceipt:
    status: int
    content_sha256: str
    not_modified: bool = False
```

For offline monitor sources, hash the raw fixture body that represents the HTTP response. For live sources, use Gather's accountable fetch path and existing receipt. Pass the resulting state to the existing `verify_ledger` after every `monitor_pass`. A private target must be replaced with a stable opaque source ID in any shared monitoring projection while the full local state may retain the target.

- [ ] **Step 4: Implement history archival and chain**

Archive the three prior current artifacts under the next zero-padded sequence before writing a new current view. Compute:

```python
def history_root(receipt_bytes: Iterable[bytes]) -> str:
    previous = ""
    for body in receipt_bytes:
        previous = hashlib.sha256((previous + sha256_bytes(body)).encode("ascii")).hexdigest()
    return previous
```

History filenames and order are closed. Extra or missing history members make verification fail.

- [ ] **Step 5: Implement `refresh_pilot`**

Sequence:

1. call `verify_pilot`;
2. refuse unless `.ok`;
3. load only `manifest.json` inside the artifact root;
4. reconstruct and validate it relative to the artifact root;
5. archive the current report and receipt;
6. capture monitored sources with `refresh=True`;
7. append successful items and per-source run evidence;
8. call `monitor_pass`;
9. verify the returned ledger;
10. atomically write state, report, HTML, and receipt.

The function accepts no manifest or policy override.

- [ ] **Step 6: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot_refresh.py tests/test_monitor.py -q
python -m ruff check src/gather/pilot.py tests/test_pilot_refresh.py
python -m mypy src/gather/pilot.py
```

- [ ] **Step 7: Commit**

```text
git add src/gather/pilot.py tests/test_pilot_refresh.py
git commit -m "feat: refresh pilots with monitored history"
```

---

## Task 6: Deterministic Shared and Full Bundles

**Files:**

- Create: `src/gather/pilot_bundle.py`
- Create: `tests/test_pilot_bundle.py`

### Contract to implement

Shared bundle members:

```text
bundle-receipt.json
manifest-digest.json
pilot-receipt.json
report.html
report.json
```

Full bundle contains the verified artifact root plus `bundle-receipt.json`. Full requires `include_private_evidence=True`.

- [ ] **Step 1: Write privacy, confirmation, determinism, and tamper tests**

Assert:

- shared bundle omits `corpus/`, `monitor-state.json`, `history/`, targets, local roots, browser hosts, credential names, private values, and absolute paths;
- shared bundle refuses `report_private_content=true`;
- full refuses without explicit confirmation;
- repeated bundle creation produces identical bytes;
- member timestamps equal `(1980, 1, 1, 0, 0, 0)`;
- all paths are relative POSIX paths without `..`;
- changing one member breaks verification.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_bundle.py -q
```

- [ ] **Step 3: Implement receipt and safe member selection**

```python
@dataclass(frozen=True, slots=True)
class PilotBundleReceipt:
    schema: str
    visibility: str
    source_receipt_sha256: str
    members: tuple[tuple[str, str], ...]
    bundle_digest: str
```

`manifest-digest.json` includes only schema, pilot ID, manifest digest, deployment, mission/source IDs, adapters, visibility, and source outcomes.

- [ ] **Step 4: Implement deterministic ZIP writing**

Use `ZIP_STORED` to avoid cross-zlib variance and explicit `ZipInfo`:

```python
def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info
```

Sort member names, write to a sibling temporary file, verify it, and `os.replace` only after success. Remove the temporary file on failure. Never overwrite the source artifact root.

- [ ] **Step 5: Define the non-recursive bundle digest**

The `bundle_digest` is SHA-256 over canonical JSON containing `schema`, `visibility`, `source_receipt_sha256`, and sorted member `(path, sha256)` pairs, excluding both `bundle_digest` and `bundle-receipt.json`. Verification re-derives that value, then verifies every listed member digest and rejects unlisted members.

- [ ] **Step 6: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot_bundle.py -q
python -m ruff check src/gather/pilot_bundle.py tests/test_pilot_bundle.py
python -m mypy src/gather/pilot_bundle.py
```

- [ ] **Step 7: Commit**

```text
git add src/gather/pilot_bundle.py tests/test_pilot_bundle.py
git commit -m "feat: package deterministic pilot bundles"
```

---

## Task 7: CLI Command Group and Exit Semantics

**Files:**

- Create: `src/gather/pilot_commands.py`
- Modify: `src/gather/cli.py`
- Create: `tests/test_pilot_cli.py`

### Contract to implement

```text
gather pilot run MANIFEST --output DIR
gather pilot refresh DIR
gather pilot verify DIR
gather pilot bundle DIR --output FILE --visibility shared
gather pilot bundle DIR --output FILE --visibility full --include-private-evidence
```

Manifest refusal exits `2`; required source or verification failure exits `1`; success exits `0`.

- [ ] **Step 1: Write parser, JSON output, partial failure, and exit-code tests**

Call `gather.cli.main` directly. Cover help, all four actions, invalid manifest, non-empty output, required source failure with report still written, verification tamper, shared bundle, full confirmation refusal, and no traceback/private diagnostic in stderr.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```text
python -m pytest tests/test_pilot_cli.py -q
```

- [ ] **Step 3: Add the nested argparse command group**

```python
pilot = sub.add_parser("pilot", help="run, refresh, verify, and bundle accountable research pilots")
pilot_sub = pilot.add_subparsers(dest="pilot_action", required=True)

run = pilot_sub.add_parser("run")
run.add_argument("manifest")
run.add_argument("--output", required=True)
run.add_argument("--json", action="store_true")
run.set_defaults(func=cmd_pilot_run)

refresh = pilot_sub.add_parser("refresh")
refresh.add_argument("output_dir")
refresh.add_argument("--json", action="store_true")
refresh.set_defaults(func=cmd_pilot_refresh)

verify = pilot_sub.add_parser("verify")
verify.add_argument("output_dir")
verify.add_argument("--json", action="store_true")
verify.set_defaults(func=cmd_pilot_verify)

bundle = pilot_sub.add_parser("bundle")
bundle.add_argument("output_dir")
bundle.add_argument("--output", required=True, dest="bundle_output")
bundle.add_argument("--visibility", choices=("shared", "full"), required=True)
bundle.add_argument("--include-private-evidence", action="store_true")
bundle.add_argument("--json", action="store_true")
bundle.set_defaults(func=cmd_pilot_bundle)
```

- [ ] **Step 4: Implement command functions as thin adapters**

Every command calls the public pilot function and emits the same result dictionaries used by MCP. Catch only expected `ValueError`, `PilotRefusal`, and verification errors. Unexpected programming errors must still surface in tests.

Required-source completion:

```python
def pilot_exit_code(manifest: PilotManifest, result: PilotResult) -> int:
    required = {
        source.id
        for mission in manifest.missions
        for source in mission.sources
        if source.required
    }
    return 0 if all(
        outcome.source_id not in required or outcome.status == "CAPTURED"
        for outcome in result.source_outcomes
    ) else 1
```

- [ ] **Step 5: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_pilot_cli.py tests/test_cli.py -q
python -m ruff check src/gather/cli.py src/gather/pilot_commands.py tests/test_pilot_cli.py
python -m mypy src/gather/cli.py src/gather/pilot_commands.py
```

- [ ] **Step 6: Commit**

```text
git add src/gather/cli.py src/gather/pilot_commands.py tests/test_pilot_cli.py
git commit -m "feat: expose pilot workflow in the CLI"
```

---

## Task 8: MCP Parity and Operator Status

**Files:**

- Modify: `src/gather/mcp.py`
- Modify: `src/gather/flagship.py`
- Modify: `tests/test_mcp.py`
- Modify: `tests/test_flagship_cli.py`

### Contract to implement

Add one `gather.pilot` tool with `run`, `refresh`, `verify`, and `bundle`. It accepts an inline manifest or manifest path for `run`, uses the same action functions as CLI, and accepts no refresh/bundle policy override.

- [ ] **Step 1: Write tool-schema and CLI/MCP parity tests**

Run the same offline manifest through CLI and MCP into separate roots under a fixed clock seam. Compare:

- report schema;
- manifest digest;
- source outcomes;
- corpus digest;
- verification verdict;
- report digest.

Also reject unknown action, missing output, run without manifest, refresh with manifest, bundle without visibility, and full bundle without confirmation.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```text
python -m pytest tests/test_mcp.py tests/test_flagship_cli.py -q
```

- [ ] **Step 3: Add the closed MCP schema**

```python
{
    "name": "gather.pilot",
    "description": "Run, refresh, verify, or bundle a controlled Gather pilot.",
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["run", "refresh", "verify", "bundle"]},
            "manifest": {"oneOf": [{"type": "string"}, {"type": "object"}]},
            "output": {"type": "string"},
            "bundle_output": {"type": "string"},
            "visibility": {"type": "string", "enum": ["shared", "full"]},
            "include_private_evidence": {"type": "boolean"},
        },
        "required": ["action", "output"],
    },
}
```

- [ ] **Step 4: Implement MCP through shared action helpers**

For an inline manifest, validate the object with `Path.cwd()` as the base and snapshot only the normalized result. Return a JSON object with action, report payload or verification, relative artifact paths, and collected events. Do not add source bodies or private targets to the response.

- [ ] **Step 5: Align status and doctor truth**

Update:

```python
PRIMARY_COMMANDS = ["docs", "web", "feed", "pdf", "run", "pilot", "corpus", "federation"]
```

Advertise `gather.pilot`, replace the stale hard-coded `1.5.0` current status with `__version__`, and add a general doctor check for `pilot_engine` without claiming optional executable availability.

- [ ] **Step 6: Run focused tests and static checks**

Run:

```text
python -m pytest tests/test_mcp.py tests/test_flagship_cli.py -q
python -m ruff check src/gather/mcp.py src/gather/flagship.py tests/test_mcp.py tests/test_flagship_cli.py
python -m mypy src/gather/mcp.py src/gather/flagship.py
```

- [ ] **Step 7: Commit**

```text
git add src/gather/mcp.py src/gather/flagship.py tests/test_mcp.py tests/test_flagship_cli.py
git commit -m "feat: add pilot MCP parity and status"
```

---

## Task 9: Representative Offline and Controlled-Live Showcases

**Files:**

- Create: `examples/pilot/showcase-offline.json`
- Create: `examples/pilot/showcase-live.json`
- Create: `examples/pilot/fixtures/venture/portfolio-v1.html`
- Create: `examples/pilot/fixtures/venture/portfolio-v2.html`
- Create: `examples/pilot/fixtures/venture/founder.html`
- Create: `examples/pilot/fixtures/technical/release.html`
- Create: `examples/pilot/fixtures/technical/scholar.json`
- Create: `examples/pilot/fixtures/media/newsroom.xml`
- Create: `examples/pilot/fixtures/media/video.json`
- Create: `examples/pilot/fixtures/media/records.json`
- Create: `examples/pilot/fixtures/private/operator-memo.txt`
- Create: `tests/test_pilot_showcase.py`

### Contract to implement

All fixtures are original synthetic repository content. The offline showcase has exactly three missions and exercises web, feed, scholar, video, API, and docs replay, public/private visibility, deduplication, extraction, monitoring, redaction, and refresh.

- [ ] **Step 1: Write the end-to-end showcase test before fixtures**

```python
def test_offline_showcase_is_deterministic_and_verifiable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network opened")),
    )
    manifest_path = Path("examples/pilot/showcase-offline.json")
    one = tmp_path / "one"
    two = tmp_path / "two"

    run_pilot(load_pilot_manifest(manifest_path), one, clock=lambda: 1700000000.0)
    run_pilot(load_pilot_manifest(manifest_path), two, clock=lambda: 1700000000.0)

    assert json.loads((one / "report.json").read_text()) == json.loads(
        (two / "report.json").read_text()
    )
    assert verify_pilot(one).ok
    assert verify_pilot(two).ok
```

Also assert three mission IDs, at least six adapters, one private source, a grounded extraction, dedup count, `NEW`, then `CHANGED`, then `UNCHANGED`.

- [ ] **Step 2: Run the test and confirm it fails because fixtures are absent**

Run:

```text
python -m pytest tests/test_pilot_showcase.py -q
```

- [ ] **Step 3: Write original fixtures**

Keep fixture bodies small and internally coherent:

- venture portfolio v1/v2 changes one product status;
- founder page contains structured organization/name fields;
- technical release includes a version and two features;
- Scholar payload includes two providers for one DOI and one citation edge;
- newsroom feed has two entries;
- video fixture has `info_json`, VTT, and one comment;
- API has two canonical records;
- private memo has no real person, customer, or secret.

Use fictional names and domains reserved for examples.

- [ ] **Step 4: Write the offline manifest**

Use:

```json
{
  "schema": "gather.pilot-manifest/1",
  "pilot_id": "zentropy-representative-showcase",
  "title": "Gather representative research operations pilot",
  "mode": "offline",
  "deployment": {"mode": "workstation", "custodian": "customer"},
  "policy": {
    "allowed_hosts": [],
    "trusted_browser_hosts": [],
    "allowed_local_roots": ["./fixtures"],
    "enabled_adapters": ["web", "feed", "docs", "scholar", "video", "api"],
    "credentials": [],
    "report_private_content": false
  },
  "missions": []
}
```

Populate exactly `venture-market-diligence`, `technical-scientific-research`, and `media-operational-intelligence`.

- [ ] **Step 5: Write the controlled-live template**

Use public example targets only where stable and mark external availability as a limitation. Include exact allowed hosts, no wildcard, no credentials, no fixtures, and browser disabled by default. The live file is a template and is not part of offline CI.

- [ ] **Step 6: Run focused tests and generate temporary sample artifacts**

Run:

```text
python -m pytest tests/test_pilot_showcase.py -q
python -m gather pilot run examples/pilot/showcase-offline.json --output .tmp-pilot-showcase --json
python -m gather pilot refresh .tmp-pilot-showcase --json
python -m gather pilot verify .tmp-pilot-showcase --json
```

Inspect `report.html` in a browser and verify no layout overflow, remote request, unescaped markup, or private target appears.

- [ ] **Step 7: Remove only the verified temporary showcase root**

Resolve `.tmp-pilot-showcase` to an absolute path under the Gather repository, confirm that boundary, then remove that one directory with native PowerShell:

```text
$pilotTemp = (Resolve-Path .tmp-pilot-showcase).Path
if (-not $pilotTemp.StartsWith((Resolve-Path .).Path)) { throw "refusing out-of-repo delete" }
Remove-Item -LiteralPath $pilotTemp -Recurse -Force
```

- [ ] **Step 8: Commit**

```text
git add examples/pilot tests/test_pilot_showcase.py
git commit -m "feat: add representative Gather pilot showcase"
```

---

## Task 10: Checked-In Redacted Evidence Sample and Public Documentation

**Files:**

- Create: `docs/PILOT.md`
- Create: `examples/pilot/README.md`
- Create: `examples/pilot/sample/report.json`
- Create: `examples/pilot/sample/report.html`
- Create: `examples/pilot/sample/pilot-receipt.json`
- Create: `examples/pilot/sample/manifest-digest.json`
- Create: `examples/pilot/sample/bundle-receipt.json`
- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `CHANGELOG.md`
- Create: `tests/test_pilot_sample.py`

### Contract to implement

The checked-in sample is generated from the offline showcase, redacted, verified, reproducible, and factual. Public text states Gather is retained by Zentropy Labs and makes no acquisition, customer, market-fit, source-truth, or external-availability claim.

- [ ] **Step 1: Write sample drift tests**

The test regenerates an offline run and shared bundle under the fixed clock, then compares semantic payloads and receipt digests with checked-in sample files. It scans for:

- absolute Windows and POSIX paths;
- fixture/private bodies;
- credential-like strings;
- remote HTML assets;
- PSL, contact, pricing, negotiation, or acquisition language.

- [ ] **Step 2: Run the focused test and confirm it fails because sample files are absent**

Run:

```text
python -m pytest tests/test_pilot_sample.py -q
```

- [ ] **Step 3: Generate and copy only redacted sample artifacts**

Generate to an ignored temporary root under the repository. Copy:

- current redacted report JSON and HTML;
- current pilot receipt;
- shared `manifest-digest.json`;
- shared `bundle-receipt.json`.

Do not check in the corpus, full bundle, monitor state, history, or normalized manifest.

- [ ] **Step 4: Write `docs/PILOT.md`**

Include:

- customer outcome;
- three representative mission classes;
- workstation, customer-hosted, and Zentropy-managed deployment choices;
- manifest safety boundary and browser limitation;
- run, refresh, verify, and bundle commands;
- artifact inventory and independent verification;
- private/shared evidence boundary;
- retained-capability statement;
- explicit `Limitations` and `Does Not Prove` sections backed by the report's
  `limitations` and `does_not_prove` fields;
- link to the SaaS roadmap without claiming the later subprojects are shipped.

- [ ] **Step 5: Write the example runbook and update public index files**

`examples/pilot/README.md` gives exact offline commands and explains expected `NEW`, `CHANGED`, and `UNCHANGED` observations.

Update:

- `README.md` feature list, quickstart link, and truthful test count;
- `USAGE.md` command reference and exit codes;
- `CHANGELOG.md` under `Unreleased`;
- stale operator status copy already corrected in Task 8.

Do not bump or publish a release version in this task.

- [ ] **Step 6: Run documentation and sample checks**

Run:

```text
python -m pytest tests/test_pilot_sample.py tests/test_pilot_showcase.py -q
python -m ruff check src tests examples
python -m mypy src
python -m public_surface_sweeper . --workspace --json
```

If `public_surface_sweeper` is unavailable, record the exact missing checkout or import as a blocked external gate. Do not claim it passed.

- [ ] **Step 7: Commit**

```text
git add docs/PILOT.md examples/pilot README.md USAGE.md CHANGELOG.md tests/test_pilot_sample.py
git commit -m "docs: publish the Gather pilot evidence package"
```

---

## Task 11: Full Verification and Release Evidence

**Files:**

- Modify only if a verification failure proves a defect in a prior task.

- [ ] **Step 1: Install the editable development package**

Run:

```text
python -m pip install -e ".[dev]"
```

- [ ] **Step 2: Run focused pilot coverage**

Run:

```text
python -m pytest tests/test_pilot_manifest.py tests/test_pilot_sources.py tests/test_pilot.py tests/test_pilot_report.py tests/test_pilot_refresh.py tests/test_pilot_bundle.py tests/test_pilot_cli.py tests/test_pilot_showcase.py tests/test_pilot_sample.py -q
```

- [ ] **Step 3: Run the complete repository gates**

Run:

```text
python -m pytest
python -m ruff check src tests examples
python -m mypy src
gather status --json
gather doctor --json
```

Record fresh test totals and command verdicts. Do not reuse the preimplementation baseline.

- [ ] **Step 4: Exercise the installed CLI end to end**

Use a new explicit temporary directory:

```text
gather pilot run examples/pilot/showcase-offline.json --output .tmp-pilot-acceptance --json
gather pilot refresh .tmp-pilot-acceptance --json
gather pilot refresh .tmp-pilot-acceptance --json
gather pilot verify .tmp-pilot-acceptance --json
gather pilot bundle .tmp-pilot-acceptance --output .tmp-pilot-acceptance.zip --visibility shared
```

Expected evidence:

- initial monitor count includes `NEW`;
- first refresh includes `CHANGED`;
- second refresh includes `UNCHANGED`;
- verification returns `ok: true`;
- shared bundle verifies;
- no required source is outside `CAPTURED`.

- [ ] **Step 5: Perform deliberate tamper verification against a copy**

Copy the acceptance root to `.tmp-pilot-tamper`, alter one corpus object byte, and run:

```text
gather pilot verify .tmp-pilot-tamper --json
```

Expected: exit `1`, `corpus_verified: false`, and no mutation of the source acceptance root.

- [ ] **Step 6: Inspect report and bundle privacy**

Open the acceptance `report.html` locally. List the shared ZIP members and extract it to a new temporary directory. Search all extracted text for the private fixture body, absolute repository path, credential names, and `http://` or `https://` remote assets in HTML. All searches must return no leak.

- [ ] **Step 7: Remove only the explicit temporary artifacts**

Resolve and confirm each target remains under the repository before deleting:

- `.tmp-pilot-acceptance/`
- `.tmp-pilot-tamper/`
- `.tmp-pilot-bundle-check/`
- `.tmp-pilot-acceptance.zip`

- [ ] **Step 8: Review the diff and commit any verification-only fixes**

Run:

```text
git status --short
git diff --check
git log --oneline --decorate -12
```

If verification required no code change, do not create an empty commit. If it exposed a defect, return to the failing task's red-green cycle, commit that scoped fix, and rerun the full gates.

## Plan Completion Gate

Before declaring subproject 1 complete, confirm all of the following from fresh command output:

- Every acceptance criterion in section 14 of the approved engine specification maps to a passing test or an inspected artifact.
- Offline execution opened no network path.
- CLI and MCP called the same pilot functions and returned the same semantic result.
- Shared bundle inspection found no private target, body, credential value, or absolute path.
- The report and all receipts independently verified.
- The checked-in sample regenerated without semantic drift.
- Full pytest, Ruff, and mypy gates passed.
- `gather status --json` and `gather doctor --json` described the shipped state.
- No production deployment or external outreach occurred.
