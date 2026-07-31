from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from gather.digest import digest_of_receipts
from gather.item import Item, make_item
from gather.pilot_manifest import PilotManifest, validate_pilot_manifest
from gather.pilot_sources import AdapterUnavailable, CapturedSource
from gather.schema_extract import Field
from gather.store import Corpus


class CollectingSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def sample_item(item_id: str) -> Item:
    return make_item(
        kind="document",
        id=item_id,
        title=f"Title {item_id}",
        text=f"Body {item_id}",
        source="docs",
        ref=item_id,
        method="read",
        fetched_at=1700000000.0,
    )


def source_data(source_id: str, *, required: bool = True) -> dict[str, object]:
    return {
        "id": source_id,
        "adapter": "docs",
        "target": "fixtures/source.txt",
        "fixture": None,
        "refresh_fixture": None,
        "visibility": "private",
        "monitor": False,
        "required": required,
        "extraction": None,
        "options": {},
    }


def two_source_manifest(tmp_path: Path, *, required_second: bool) -> PilotManifest:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "source.txt").write_text("fixture", encoding="utf-8")
    return validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "pilot-one",
            "title": "Pilot",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": [],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["docs"],
                "credentials": ["PILOT_SECRET"],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "mission-one",
                    "title": "Mission",
                    "sources": [
                        source_data("source-one"),
                        source_data("source-two", required=required_second),
                    ],
                }
            ],
        },
        tmp_path,
    )


def next_or_raise(values):
    value = next(values)
    if isinstance(value, BaseException):
        raise value
    return value


def test_source_failure_does_not_erase_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([CapturedSource((sample_item("kept"),)), RuntimeError("upstream refused")])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))
    events = CollectingSink()

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0, event_sink=events)

    assert [outcome.status for outcome in result.source_outcomes] == ["CAPTURED", "ERROR"]
    assert Corpus(str(tmp_path / "out" / "corpus")).stats()["items"] == 1
    assert [event.sequence for event in events.events] == list(range(1, len(events.events) + 1))
    assert all("upstream" not in json.dumps(asdict(event)) for event in events.events)


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        (CapturedSource(()), "EMPTY"),
        (AdapterUnavailable("missing executable"), "UNAVAILABLE"),
    ],
)
def test_empty_and_unavailable_sources_have_typed_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: object, expected: str
) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([captured, CapturedSource(())])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0)

    assert result.source_outcomes[0].status == expected
    assert result.source_outcomes[0].item_count == 0


def test_refused_source_and_credential_diagnostic_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import PilotRefusal, run_pilot

    monkeypatch.setenv("PILOT_SECRET", "credential-value")
    manifest = two_source_manifest(tmp_path, required_second=True)
    calls = iter([PilotRefusal("refused credential-value"), CapturedSource(())])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0)

    assert result.source_outcomes[0].status == "REFUSED"
    assert result.source_outcomes[0].diagnostic == "refused [REDACTED]"
    assert result.source_outcomes[0].status != "CAPTURED"


def test_receipt_digest_seals_items_and_receipt_only_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    item = sample_item("work")
    edge = {
        "kind": "citation-edge",
        "id": "edge-one",
        "title": "work -> prior-work",
        "source": "scholar",
        "ref": "openalex",
        "method": "citation-edge",
        "sha256": "a" * 64,
        "derived_from": [],
    }
    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([CapturedSource((item,), (edge,)), CapturedSource(())])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0)
    corpus = Corpus(str(tmp_path / "out" / "corpus"))
    expected = digest_of_receipts(list(corpus.rows()) + [edge])

    assert result.source_outcomes[0].receipt_digests == tuple(
        receipt["sha256"] for receipt in expected.receipts
    )
    assert next(corpus.runs())["digest_seal"] == expected.seal


def test_missing_required_extraction_makes_source_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    source = manifest.missions[0].sources[0]
    object.__setattr__(source, "extraction", {"title": Field("h1", required=True)})
    calls = iter([CapturedSource((sample_item("item"),), extraction_html="<p>no title</p>"), CapturedSource(())])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0)

    assert result.source_outcomes[0].status == "ERROR"
    assert result.extraction_outcomes[0].missing_required == ("title",)
    assert Corpus(str(tmp_path / "out" / "corpus")).stats()["items"] == 0


def test_output_directory_must_be_empty(tmp_path: Path) -> None:
    from gather.pilot import PilotRefusal, run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    output = tmp_path / "out"
    output.mkdir()
    (output / "existing.txt").write_text("occupied", encoding="utf-8")

    with pytest.raises(PilotRefusal, match="not empty"):
        run_pilot(manifest, output, clock=lambda: 1700000000.0)


def test_public_outcome_and_event_types_refuse_open_vocabularies() -> None:
    from gather.pilot import PilotEvent, SourceOutcome

    with pytest.raises(ValueError, match="status"):
        SourceOutcome("mission", "source", "docs", "private", "UNKNOWN", 0, (), "")
    with pytest.raises(ValueError, match="kind"):
        PilotEvent(1, "leaky_event", "mission", "source", "ERROR")


def test_pilot_verification_serializes_only_its_closed_contract() -> None:
    from gather.pilot import PilotVerification

    verification = PilotVerification(True, True, True, True, None, True)

    assert verification.ok
    assert set(verification.to_dict()) == {
        "manifest_verified",
        "report_verified",
        "html_verified",
        "corpus_verified",
        "monitor_verified",
        "receipt_verified",
    }


def test_missing_run_witness_marks_persisted_source_error_and_result_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([CapturedSource((sample_item("first"),)), CapturedSource((sample_item("second"),))])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))
    original_add_record = Corpus.add_record
    writes = 0

    def fail_first_witness(self: Corpus, record: dict) -> None:
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("run witness unavailable")
        original_add_record(self, record)

    monkeypatch.setattr(Corpus, "add_record", fail_first_witness)

    result = run_pilot(manifest, tmp_path / "out", clock=lambda: 1700000000.0)

    assert [outcome.status for outcome in result.source_outcomes] == ["ERROR", "CAPTURED"]
    assert Corpus(str(tmp_path / "out" / "corpus")).stats()["items"] == 2
    assert not result.corpus_verified


class FailingSink:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def emit(self, event: object) -> None:
        if getattr(event, "kind") == self.kind:
            raise RuntimeError(f"observer failed during {self.kind}")


def test_source_started_observer_failure_does_not_abort_or_reclassify_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([CapturedSource((sample_item("first"),)), CapturedSource((sample_item("second"),))])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(
        manifest,
        tmp_path / "out",
        clock=lambda: 1700000000.0,
        event_sink=FailingSink("source_started"),
    )

    assert [outcome.status for outcome in result.source_outcomes] == ["CAPTURED", "CAPTURED"]
    assert len(result.source_outcomes) == 2


def test_source_completed_observer_failure_does_not_duplicate_an_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gather.pilot import run_pilot

    manifest = two_source_manifest(tmp_path, required_second=False)
    calls = iter([CapturedSource((sample_item("first"),)), CapturedSource((sample_item("second"),))])
    monkeypatch.setattr("gather.pilot.capture_source", lambda *_a, **_k: next_or_raise(calls))

    result = run_pilot(
        manifest,
        tmp_path / "out",
        clock=lambda: 1700000000.0,
        event_sink=FailingSink("source_completed"),
    )

    assert [outcome.status for outcome in result.source_outcomes] == ["CAPTURED", "CAPTURED"]
    assert len(result.source_outcomes) == 2
