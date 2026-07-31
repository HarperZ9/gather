from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gather.item import Item, make_item
from gather.pilot import ExtractionOutcome, PilotResult, SourceOutcome
from gather.pilot_manifest import PilotManifest, validate_pilot_manifest
from gather.pilot_sources import CapturedSource
from gather.store import Corpus


def _source_data(target: str = "fixtures/secret-plan.txt") -> dict[str, object]:
    return {
        "id": "source-one",
        "adapter": "docs",
        "target": target,
        "fixture": None,
        "refresh_fixture": None,
        "visibility": "private",
        "monitor": False,
        "required": True,
        "extraction": None,
        "options": {},
    }


def _manifest(tmp_path: Path, *, target: str = "fixtures/secret-plan.txt") -> PilotManifest:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "secret-plan.txt").write_text("private body", encoding="utf-8")
    return validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "pilot-one",
            "title": "Evidence pilot",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": [],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["docs"],
                "credentials": [],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "mission-one",
                    "title": "Private mission",
                    "sources": [_source_data(target)],
                }
            ],
        },
        tmp_path,
    )


def _item() -> Item:
    return make_item(
        kind="document",
        id="private-item",
        title="Secret plan title",
        text="Private source body",
        source="docs",
        ref="C:/clients/secret-plan.txt",
        method="read",
        fetched_at=1700000000.0,
    )


def _result() -> PilotResult:
    return PilotResult(
        manifest_sha256="a" * 64,
        source_outcomes=(
            SourceOutcome(
                "mission-one",
                "source-one",
                "docs",
                "private",
                "CAPTURED",
                1,
                ("b" * 64,),
                "diagnostic C:/clients/secret-plan.txt",
            ),
        ),
        extraction_outcomes=(
            ExtractionOutcome(
                "source-one",
                (
                    {
                        "name": "organization",
                        "value": "Secret Plan LLC",
                        "status": "MATCH",
                        "attr": None,
                        "many": False,
                        "required": True,
                        "hits": [
                            {
                                "value": "Secret Plan LLC",
                                "path": "html/body/main/h1",
                                "source_sha256": "c" * 64,
                                "value_sha256": "d" * 64,
                            }
                        ],
                    },
                ),
                (),
                True,
            ),
        ),
        corpus_digest="e" * 64,
        corpus_verified=True,
        monitor_report=None,
        monitor_verified=None,
        limitations=("Captured statements are not established as true.",),
        does_not_prove=("truth of source claims",),
    )


def _rebind_current(root: Path, report: dict[str, object]) -> None:
    from gather.pilot_report import canonical_json_bytes, render_report_html

    semantic = dict(report)
    semantic.pop("report_digest", None)
    report["report_digest"] = hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()
    report_body = canonical_json_bytes(report)
    html_body = render_report_html(report).encode("utf-8")
    (root / "report.json").write_bytes(report_body)
    (root / "report.html").write_bytes(html_body)
    receipt_path = root / "pilot-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["manifest_sha256"] = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    receipt["report_json_sha256"] = hashlib.sha256(report_body).hexdigest()
    receipt["report_html_sha256"] = hashlib.sha256(html_body).hexdigest()
    receipt["semantic_report_sha256"] = report["report_digest"]
    receipt["monitor_root_hash"] = report["monitoring"]["root_hash"]  # type: ignore[index]
    receipt["history_count"] = report["history_count"]
    receipt_path.write_bytes(canonical_json_bytes(receipt))


def _reseal_run(row: dict[str, object]) -> dict[str, object]:
    from gather.run import RunRecord, _record_fields, _seal_record

    record = RunRecord.from_dict(row)
    fields = _record_fields(
        record.started_at,
        record.targets,
        record.scope,
        record.gathered,
        record.kept,
        record.dropped,
        record.synthesized,
        record.digested,
        record.origins,
        record.digest_seal,
        record.stored,
    )
    row["seal"] = _seal_record(fields)
    return row


def _two_source_manifest(tmp_path: Path) -> PilotManifest:
    manifest = _manifest(tmp_path)
    second = tmp_path / "fixtures" / "second.txt"
    second.write_text("second body", encoding="utf-8")
    data = json.loads((json.dumps({
        "schema": manifest.schema,
        "pilot_id": manifest.pilot_id,
        "title": manifest.title,
        "mode": manifest.mode,
        "deployment": {
            "mode": manifest.deployment.mode,
            "custodian": manifest.deployment.custodian,
        },
        "policy": {
            "allowed_hosts": [],
            "trusted_browser_hosts": [],
            "allowed_local_roots": ["fixtures"],
            "enabled_adapters": ["docs"],
            "credentials": [],
            "report_private_content": False,
        },
        "missions": [{
            "id": "mission-one",
            "title": "Private mission",
            "sources": [
                _source_data(),
                {**_source_data("fixtures/second.txt"), "id": "source-two"},
            ],
        }],
    })))
    return validate_pilot_manifest(data, tmp_path)


def _monitored_manifest(tmp_path: Path) -> PilotManifest:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "source.html").write_text("<h1>Evidence</h1>", encoding="utf-8")
    return validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "monitor-one",
            "title": "Monitored pilot",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": ["example.com"],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["web"],
                "credentials": [],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "monitor-mission",
                    "title": "Monitor mission",
                    "sources": [
                        {
                            "id": "monitored-source",
                            "adapter": "web",
                            "target": "https://example.com/evidence",
                            "fixture": "fixtures/source.html",
                            "refresh_fixture": None,
                            "visibility": "public",
                            "monitor": True,
                            "required": True,
                            "extraction": None,
                            "options": {},
                        }
                    ],
                }
            ],
        },
        tmp_path,
    )


def _history_chain(receipts: list[bytes]) -> str:
    previous = ""
    for body in receipts:
        previous = hashlib.sha256(
            (previous + hashlib.sha256(body).hexdigest()).encode("ascii")
        ).hexdigest()
    return previous


def _archive_current(root: Path, sequence: int) -> bytes:
    prefix = f"{sequence:04d}"
    for name in ("report.json", "report.html", "pilot-receipt.json"):
        (root / "history" / f"{prefix}-{name}").write_bytes((root / name).read_bytes())
    return (root / "history" / f"{prefix}-pilot-receipt.json").read_bytes()


def test_shared_report_redacts_private_source_material(tmp_path: Path) -> None:
    from gather.pilot_report import report_payload

    payload = report_payload(_manifest(tmp_path), _result(), corpus_stats={"items": 1})
    rendered = json.dumps(payload)
    source = payload["missions"][0]["sources"][0]  # type: ignore[index]
    extraction = payload["extractions"][0]["fields"][0]  # type: ignore[index]
    hit = extraction["hits"][0]

    assert "secret-plan" not in rendered.lower()
    assert "C:/clients" not in rendered
    assert "Private source body" not in rendered
    assert "Secret Plan LLC" not in rendered
    assert "html/body" not in rendered
    assert source["visibility"] == "private"
    assert source["item_count"] == 1
    assert source["receipt_digests"]
    assert hit == {"source_sha256": "c" * 64, "value_sha256": "d" * 64}


def test_private_report_redaction_is_unconditional_when_policy_requests_content(
    tmp_path: Path,
) -> None:
    from gather.pilot_report import report_payload

    manifest = _manifest(tmp_path)
    object.__setattr__(
        manifest,
        "policy",
        replace(manifest.policy, report_private_content=True),
    )

    payload = report_payload(manifest, _result(), corpus_stats={"items": 1})
    rendered = json.dumps(payload)
    source = payload["missions"][0]["sources"][0]  # type: ignore[index]
    field = payload["extractions"][0]["fields"][0]  # type: ignore[index]

    assert "target" not in source
    assert "value" not in field
    assert "Secret Plan LLC" not in rendered
    assert "html/body/main/h1" not in rendered


def test_report_digest_excludes_only_its_own_field(tmp_path: Path) -> None:
    from gather.pilot_report import canonical_json_bytes, report_payload, sha256_bytes

    payload = report_payload(_manifest(tmp_path), _result(), corpus_stats={"items": 1})
    semantic = dict(payload)
    digest = semantic.pop("report_digest")

    assert digest == sha256_bytes(canonical_json_bytes(semantic))


def test_html_escapes_all_dynamic_values() -> None:
    from gather.pilot_report import render_report_html

    html_text = render_report_html({"title": '<img src=x onerror="alert(1)">'})

    assert "<img" not in html_text
    assert "&lt;img" in html_text
    assert "https://" not in html_text
    assert "<script" not in html_text.lower()
    assert html_text.count("<style>") == 1


def test_run_writes_canonical_report_receipt_and_terminal_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    events: list[object] = []

    class Sink:
        def emit(self, event: object) -> None:
            events.append(event)

    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0, event_sink=Sink())

    for name in ("manifest.json", "report.json", "pilot-receipt.json"):
        body = (root / name).read_bytes()
        assert body == canonical_json_bytes(json.loads(body))
    assert (root / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert [getattr(event, "kind") for event in events][-2:] == [
        "report_written",
        "run_completed",
    ]
    assert verify_pilot(root).ok


@pytest.mark.parametrize(
    "artifact",
    [
        "manifest.json",
        "report.json",
        "report.html",
        "pilot-receipt.json",
        "corpus-body",
        "run-witness",
        "monitor-state.json",
        "history",
    ],
)
def test_verify_pilot_rejects_each_tampered_evidence_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)

    if artifact in {"manifest.json", "report.json", "pilot-receipt.json"}:
        path = root / artifact
        value = json.loads(path.read_bytes())
        value["tampered"] = True
        path.write_bytes(canonical_json_bytes(value))
    elif artifact == "report.html":
        (root / artifact).write_text("<p>tampered</p>", encoding="utf-8")
    elif artifact == "corpus-body":
        row = next(Corpus(str(root / "corpus")).rows())
        body = root / "corpus" / "objects" / row["sha256"][:2] / row["sha256"][2:]
        body.write_text("tampered body", encoding="utf-8")
    elif artifact == "run-witness":
        path = root / "corpus" / "runs.jsonl"
        row = json.loads(path.read_text(encoding="utf-8"))
        row["kept"] += 1
        path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    elif artifact == "monitor-state.json":
        path = root / artifact
        state = json.loads(path.read_bytes())
        state["root_hash"] = "f" * 64
        path.write_bytes(canonical_json_bytes(state))
    else:
        (root / "history" / "unexpected").write_text("tampered", encoding="utf-8")

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_escaping_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    receipt_path = root / "pilot-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["artifacts"]["manifest"] = "../manifest.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_rebound_html_that_is_not_the_report_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    html_body = b"<!doctype html><html><body>different view</body></html>"
    (root / "report.html").write_bytes(html_body)
    receipt_path = root / "pilot-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["report_html_sha256"] = hashlib.sha256(html_body).hexdigest()
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_rebound_report_identity_that_disagrees_with_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes, render_report_html

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report_path = root / "report.json"
    report = json.loads(report_path.read_bytes())
    report["pilot_id"] = "different-pilot"
    report.pop("report_digest")
    report["report_digest"] = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    report_body = canonical_json_bytes(report)
    html_body = render_report_html(report).encode("utf-8")
    report_path.write_bytes(report_body)
    (root / "report.html").write_bytes(html_body)
    receipt_path = root / "pilot-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["report_json_sha256"] = hashlib.sha256(report_body).hexdigest()
    receipt["report_html_sha256"] = hashlib.sha256(html_body).hexdigest()
    receipt["semantic_report_sha256"] = report["report_digest"]
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    assert not verify_pilot(root).ok


def test_failed_receipt_write_emits_no_report_or_completion_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    events: list[object] = []

    class Sink:
        def emit(self, event: object) -> None:
            events.append(event)

    def fail_receipt(*_args: object, **_kwargs: object) -> None:
        raise OSError("receipt unavailable")

    monkeypatch.setattr("gather.pilot_report.build_pilot_receipt", fail_receipt)

    with pytest.raises(OSError, match="receipt unavailable"):
        run_pilot(
            manifest,
            tmp_path / "out",
            clock=lambda: 1700000000.0,
            event_sink=Sink(),
        )

    assert "report_written" not in [getattr(event, "kind") for event in events]
    assert "run_completed" not in [getattr(event, "kind") for event in events]


def test_verify_pilot_is_network_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network opened")),
    )

    assert verify_pilot(root).ok


def test_report_digest_changes_with_semantic_content(tmp_path: Path) -> None:
    from gather.pilot_report import report_payload

    result = _result()
    first = report_payload(_manifest(tmp_path), result, corpus_stats={"items": 1})
    second = report_payload(
        _manifest(tmp_path),
        replace(result, corpus_digest="f" * 64),
        corpus_stats={"items": 1},
    )

    assert first["report_digest"] != second["report_digest"]


def test_verify_pilot_rejects_reordered_self_sealed_source_witnesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _two_source_manifest(tmp_path)
    items = iter(
        [
            CapturedSource((_item(),)),
            CapturedSource(
                (
                    make_item(
                        kind="document",
                        id="second-item",
                        title="Second",
                        text="Second body",
                        source="docs",
                        ref="second",
                        method="read",
                        fetched_at=1700000000.0,
                    ),
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: next(items),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    runs_path = root / "corpus" / "runs.jsonl"
    rows = runs_path.read_text(encoding="utf-8").splitlines()
    runs_path.write_text("\n".join(reversed(rows)) + "\n", encoding="utf-8")

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_coherently_resealed_witness_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    runs_path = root / "corpus" / "runs.jsonl"
    row = json.loads(runs_path.read_text(encoding="utf-8"))
    row.update(
        {
            "gathered": 2,
            "kept": 2,
            "digested": 2,
            "stored": {"added": 2, "deduped": 0, "total": 2},
        }
    )
    runs_path.write_text(json.dumps(_reseal_run(row), sort_keys=True) + "\n", encoding="utf-8")

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_resealed_witness_with_false_stored_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    runs_path = root / "corpus" / "runs.jsonl"
    row = json.loads(runs_path.read_text(encoding="utf-8"))
    row["stored"] = {"added": 0, "deduped": 1, "total": 1}
    runs_path.write_text(json.dumps(_reseal_run(row), sort_keys=True) + "\n", encoding="utf-8")

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_coherently_resealed_origin_without_catalog_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.digest import digest_of_receipts
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    runs_path = root / "corpus" / "runs.jsonl"
    row = json.loads(runs_path.read_text(encoding="utf-8"))
    row["origins"][0]["sha256"] = "f" * 64
    row["digest_seal"] = digest_of_receipts(row["origins"]).seal
    runs_path.write_text(json.dumps(_reseal_run(row), sort_keys=True) + "\n", encoding="utf-8")

    assert not verify_pilot(root).ok


def test_verify_pilot_accounts_for_scholar_receipt_only_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "scholar.json").write_text("{}", encoding="utf-8")
    manifest = validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "scholar-one",
            "title": "Scholar pilot",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": ["api.openalex.org"],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["scholar"],
                "credentials": [],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "scholar-mission",
                    "title": "Scholar mission",
                    "sources": [
                        {
                            "id": "scholar-source",
                            "adapter": "scholar",
                            "target": "https://api.openalex.org/works/doi:10.1/example",
                            "fixture": "fixtures/scholar.json",
                            "refresh_fixture": None,
                            "visibility": "public",
                            "monitor": False,
                            "required": True,
                            "extraction": None,
                            "options": {
                                "providers": ["openalex"],
                                "federated": False,
                                "edges": True,
                            },
                        }
                    ],
                }
            ],
        },
        tmp_path,
    )
    item = make_item(
        kind="scholar",
        id="work-one",
        title="Work",
        text="Scholar body",
        source="scholar",
        ref="openalex",
        method="federated-metadata",
        fetched_at=1700000000.0,
    )
    edge = {
        "kind": "citation-edge",
        "id": "edge-one",
        "title": "work-one -> work-two",
        "source": "scholar",
        "ref": "openalex",
        "method": "citation-edge",
        "sha256": "a" * 64,
        "derived_from": [],
    }
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((item,), (edge,)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)

    assert verify_pilot(root).ok


def test_verify_pilot_accepts_manifest_independent_extraction_field_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.schema_extract import Field

    manifest = _monitored_manifest(tmp_path)
    source = manifest.missions[0].sources[0]
    object.__setattr__(
        source,
        "extraction",
        {
            "zeta": Field("h1"),
            "alpha": Field("h2"),
        },
    )
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource(
            (_item(),),
            extraction_html="<h1>Zeta</h1><h2>Alpha</h2>",
        ),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)

    assert verify_pilot(root).ok


@pytest.mark.parametrize(
    "level",
    [
        "root",
        "mission",
        "source",
        "capability",
        "corpus",
        "monitoring",
    ],
)
def test_verify_pilot_rejects_coherently_rehashed_unknown_report_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_bytes())
    targets = {
        "root": report,
        "mission": report["missions"][0],
        "source": report["missions"][0]["sources"][0],
        "capability": report["adapter_capabilities"][0],
        "corpus": report["corpus"],
        "monitoring": report["monitoring"],
    }
    targets[level]["unknown"] = True
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


@pytest.mark.parametrize("level", ["extraction", "field", "hit"])
def test_verify_pilot_rejects_unknown_extraction_report_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.schema_extract import Field

    manifest = _monitored_manifest(tmp_path)
    source = manifest.missions[0].sources[0]
    object.__setattr__(source, "extraction", {"organization": Field("h1")})
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource(
            (_item(),),
            extraction_html="<h1>Evidence</h1>",
        ),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_bytes())
    extraction = report["extractions"][0]
    targets = {
        "extraction": extraction,
        "field": extraction["fields"][0],
        "hit": extraction["fields"][0]["hits"][0],
    }
    targets[level]["unknown"] = True
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_coherently_rebound_non_normalized_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    snapshot = json.loads((root / "manifest.json").read_bytes())
    snapshot["policy"]["credentials"] = ["Z_TOKEN", "A_TOKEN"]
    manifest_body = canonical_json_bytes(snapshot)
    (root / "manifest.json").write_bytes(manifest_body)
    report = json.loads((root / "report.json").read_bytes())
    report["manifest_digest"] = hashlib.sha256(manifest_body).hexdigest()
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_unknown_nested_manifest_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    snapshot = json.loads((root / "manifest.json").read_bytes())
    snapshot["policy"]["unknown"] = True
    manifest_body = canonical_json_bytes(snapshot)
    (root / "manifest.json").write_bytes(manifest_body)
    report = json.loads((root / "report.json").read_bytes())
    report["manifest_digest"] = hashlib.sha256(manifest_body).hexdigest()
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_returns_false_for_malformed_network_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _monitored_manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    snapshot = json.loads((root / "manifest.json").read_bytes())
    snapshot["missions"][0]["sources"][0]["target"] = "https://example.com:bad/evidence"
    manifest_body = canonical_json_bytes(snapshot)
    (root / "manifest.json").write_bytes(manifest_body)
    report = json.loads((root / "report.json").read_bytes())
    report["manifest_digest"] = hashlib.sha256(manifest_body).hexdigest()
    report["missions"][0]["sources"][0]["target"] = "https://example.com:bad/evidence"
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_coherently_rebound_corpus_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_bytes())
    report["corpus"]["items"] = 99
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_monitor_summary_not_derived_from_verified_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.monitor import monitor_pass
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _monitored_manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    _monitor_report, state = monitor_pass(
        ["https://example.com/evidence"],
        {"schema": "gather.monitor-state/1", "baselines": {}, "ledger": [], "root_hash": ""},
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                status=200,
                content_sha256="a" * 64,
                not_modified=False,
            ),
            b"body",
        ),
        clock=lambda: 1700000001.0,
    )
    (root / "monitor-state.json").write_bytes(canonical_json_bytes(state))
    report = json.loads((root / "report.json").read_bytes())
    report["monitoring"] = {
        "present": True,
        "counts": {
            "NEW": 1,
            "UNCHANGED": 0,
            "CHANGED": 0,
            "GONE": 0,
            "ERROR": 0,
        },
        "changed_count": 99,
        "failure_count": 0,
        "root_hash": state["root_hash"],
        "verified": True,
    }
    _rebind_current(root, report)

    assert not verify_pilot(root).ok


def test_verify_pilot_rejects_archived_receipt_without_its_predecessor_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot, verify_pilot
    from gather.pilot_report import canonical_json_bytes

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_args, **_kwargs: CapturedSource((_item(),)),
    )
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    first = _archive_current(root, 1)
    report = json.loads((root / "report.json").read_bytes())
    report["history_count"] = 1
    report["refresh_sequence"] = 1
    _rebind_current(root, report)
    receipt_path = root / "pilot-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["history_root_hash"] = _history_chain([first])
    receipt_path.write_bytes(canonical_json_bytes(receipt))
    second = _archive_current(root, 2)
    report["history_count"] = 2
    report["refresh_sequence"] = 2
    _rebind_current(root, report)

    second_path = root / "history" / "0002-pilot-receipt.json"
    second_receipt = json.loads(second_path.read_bytes())
    second_receipt["history_count"] = 0
    second_receipt["history_root_hash"] = ""
    second = canonical_json_bytes(second_receipt)
    second_path.write_bytes(second)
    receipt = json.loads(receipt_path.read_bytes())
    receipt["history_root_hash"] = _history_chain([first, second])
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    assert not verify_pilot(root).ok
