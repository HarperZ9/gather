"""Source-isolated execution for closed Gather pilot manifests.

This module owns the durable evidence boundary before reports or monitoring are
rendered.  It deliberately composes the validated manifest, adapter registry,
content-addressed corpus, receipt digest, schema extraction, and run witness.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gather.digest import digest_of_receipts
from gather.item import Item
from gather.pilot_manifest import (
    PilotManifest,
    PilotSource,
    manifest_digest,
    manifest_payload,
)
from gather.pilot_sources import AdapterUnavailable, CapturedSource, capture_source
from gather.run import RunRecord, _record_fields, _seal_record, verify_record
from gather.schema_extract import SchemaExtraction, extract_schema
from gather.store import MATCH, Corpus

SOURCE_STATUSES = frozenset({"CAPTURED", "EMPTY", "UNAVAILABLE", "REFUSED", "ERROR"})
EVENT_KINDS = frozenset(
    {
        "source_started",
        "source_completed",
        "source_failed",
        "monitor_completed",
        "report_written",
        "run_completed",
    }
)

LIMITATIONS = (
    "The first pilot does not build a multi-tenant hosted SaaS.",
    "The first pilot does not add billing, accounts, or vendor-specific cloud-storage SDKs.",
    "The first pilot does not crawl unrestricted customer-provided domains.",
    "The first pilot does not claim that captured statements are true.",
    "The first pilot does not make browser navigation safe for hostile arbitrary URLs.",
    "The first pilot does not replace Gather's adapters with a new abstraction.",
    "The first pilot does not require an LLM.",
    "The first pilot does not promise complete market, scholarly, or media coverage.",
    "The first pilot does not transfer or offer Gather for acquisition.",
    "The first pilot does not send an email or contact a partner.",
)

DOES_NOT_PROVE = (
    "product-market fit",
    "customer willingness to pay",
    "comprehensive source coverage",
    "legal sufficiency for regulated retention",
    "truth of source claims",
    "correctness of OCR, transcription, or external metadata",
    "safety of unrestricted browser automation",
    "that PSL or another organization will partner, invest, advise, or purchase",
)


class PilotRefusal(RuntimeError):
    """A pilot boundary refused an otherwise requested operation."""


class _WitnessWriteError(RuntimeError):
    """Corpus items reached durable storage but their required run witness did not."""


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

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"unknown source outcome status: {self.status}")

    def to_dict(self) -> dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "source_id": self.source_id,
            "adapter": self.adapter,
            "visibility": self.visibility,
            "status": self.status,
            "item_count": self.item_count,
            "receipt_digests": list(self.receipt_digests),
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    source_id: str
    fields: tuple[dict[str, object], ...]
    missing_required: tuple[str, ...]
    verified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "fields": [dict(field) for field in self.fields],
            "missing_required": list(self.missing_required),
            "verified": self.verified,
        }


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

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_sha256": self.manifest_sha256,
            "source_outcomes": [outcome.to_dict() for outcome in self.source_outcomes],
            "extraction_outcomes": [outcome.to_dict() for outcome in self.extraction_outcomes],
            "corpus_digest": self.corpus_digest,
            "corpus_verified": self.corpus_verified,
            "monitor_report": None if self.monitor_report is None else dict(self.monitor_report),
            "monitor_verified": self.monitor_verified,
            "limitations": list(self.limitations),
            "does_not_prove": list(self.does_not_prove),
        }


@dataclass(frozen=True, slots=True)
class PilotVerification:
    manifest_verified: bool
    report_verified: bool
    html_verified: bool
    corpus_verified: bool
    monitor_verified: bool | None
    receipt_verified: bool

    @property
    def ok(self) -> bool:
        return (
            self.manifest_verified
            and self.report_verified
            and self.html_verified
            and self.corpus_verified
            and self.receipt_verified
            and self.monitor_verified in (True, None)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_verified": self.manifest_verified,
            "report_verified": self.report_verified,
            "html_verified": self.html_verified,
            "corpus_verified": self.corpus_verified,
            "monitor_verified": self.monitor_verified,
            "receipt_verified": self.receipt_verified,
        }


@dataclass(frozen=True, slots=True)
class PilotEvent:
    sequence: int
    kind: str
    mission_id: str | None
    source_id: str | None
    status: str

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown pilot event kind: {self.kind}")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "mission_id": self.mission_id,
            "source_id": self.source_id,
            "status": self.status,
        }


class PilotEventSink(Protocol):
    def emit(self, event: PilotEvent) -> None: ...


def _diagnostic(exc: BaseException, credential_names: tuple[str, ...]) -> str:
    text = " ".join(str(exc).split())
    for name in credential_names:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text[:240]


def _atomic_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _initialize_output(output_dir: Path, manifest: PilotManifest) -> Corpus:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PilotRefusal("pilot output directory is not empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "manifest.json", manifest_payload(manifest))
    (output_dir / "corpus").mkdir(exist_ok=True)
    _atomic_json(
        output_dir / "monitor-state.json",
        {"schema": "gather.monitor-state/1", "baselines": {}, "ledger": [], "root_hash": ""},
    )
    (output_dir / "history").mkdir(exist_ok=True)
    return Corpus(str(output_dir / "corpus"))


def _item_receipt(item: Item) -> dict[str, object]:
    provenance = item.provenance
    return {
        "kind": item.kind,
        "id": item.id,
        "title": item.title,
        "source": provenance.source,
        "ref": provenance.ref,
        "method": provenance.method,
        "sha256": provenance.sha256,
        "derived_from": list(provenance.derived_from),
    }


def _field_payload(extraction: SchemaExtraction) -> tuple[dict[str, object], ...]:
    fields: list[dict[str, object]] = []
    for field in extraction.fields:
        fields.append(
            {
                "name": field.name,
                "value": field.value,
                "status": field.status,
                "attr": field.attr,
                "many": field.many,
                "required": field.required,
                "hits": [
                    {
                        "value": hit.value,
                        "path": hit.path,
                        "source_sha256": hit.source_sha256,
                        "value_sha256": hit.value_sha256,
                    }
                    for hit in field.hits
                ],
            }
        )
    return tuple(fields)


def _extraction_outcome(source: PilotSource, captured: CapturedSource, at: float) -> ExtractionOutcome:
    if source.extraction is None:
        raise ValueError("source has no extraction schema")
    if captured.extraction_html is None:
        raise ValueError("source did not preserve HTML for extraction")
    extraction = extract_schema(
        captured.extraction_html,
        dict(source.extraction),
        source.target,
        fetched_at=at,
    )
    return ExtractionOutcome(
        source_id=source.id,
        fields=_field_payload(extraction),
        missing_required=tuple(extraction.missing_required()),
        verified=extraction.verify(captured.extraction_html),
    )


def _persist_source(
    corpus: Corpus,
    source: PilotSource,
    items: tuple[Item, ...],
    extra_receipts: tuple[dict[str, object], ...],
    *,
    at: float,
) -> tuple[str, ...]:
    receipts = [_item_receipt(item) for item in items] + [dict(receipt) for receipt in extra_receipts]
    digest = digest_of_receipts(receipts)
    stored = corpus.add(list(items))
    origins = tuple(digest.receipts)
    fields = _record_fields(
        at,
        ((source.adapter, source.target),),
        (),
        len(items),
        len(items),
        0,
        False,
        len(items),
        origins,
        digest.seal,
        stored,
    )
    record = RunRecord(
        started_at=at,
        targets=((source.adapter, source.target),),
        scope=(),
        gathered=len(items),
        kept=len(items),
        dropped=0,
        synthesized=False,
        digested=len(items),
        origins=origins,
        digest_seal=digest.seal,
        stored=stored,
        seal=_seal_record(fields),
    )
    try:
        corpus.add_record(record.to_dict())
    except Exception as exc:  # noqa: BLE001 - preserve the already-durable source items
        raise _WitnessWriteError("source run witness could not be recorded") from exc
    return tuple(str(receipt["sha256"]) for receipt in digest.receipts)


def _corpus_verified(corpus: Corpus) -> bool:
    try:
        return all(row.get("status") == MATCH for row in corpus.verify())
    except (OSError, ValueError):
        return False


def _runs_verified(corpus: Corpus) -> bool:
    try:
        return all(verify_record(RunRecord.from_dict(row)) for row in corpus.runs())
    except (OSError, ValueError, TypeError):
        return False


def run_pilot(
    manifest: PilotManifest,
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.time,
    event_sink: PilotEventSink | None = None,
) -> PilotResult:
    """Run every requested source once, preserving successful evidence on later failures."""
    root = Path(output_dir)
    corpus = _initialize_output(root, manifest)
    source_outcomes: list[SourceOutcome] = []
    extraction_outcomes: list[ExtractionOutcome] = []
    witnesses_complete = True
    sequence = 0

    def emit(kind: str, mission_id: str | None, source_id: str | None, status: str) -> None:
        nonlocal sequence
        if event_sink is None:
            return
        sequence += 1
        try:
            event_sink.emit(PilotEvent(sequence, kind, mission_id, source_id, status))
        except Exception:
            return

    for mission in manifest.missions:
        for source in mission.sources:
            emit("source_started", mission.id, source.id, "STARTED")
            try:
                captured = capture_source(source, manifest, clock=clock)
                if source.extraction is not None:
                    extraction = _extraction_outcome(source, captured, float(clock()))
                    extraction_outcomes.append(extraction)
                    if extraction.missing_required:
                        outcome = SourceOutcome(
                            mission.id,
                            source.id,
                            source.adapter,
                            source.visibility,
                            "ERROR",
                            0,
                            (),
                            "missing required extraction fields: " + ", ".join(extraction.missing_required),
                        )
                        source_outcomes.append(outcome)
                        emit("source_failed", mission.id, source.id, outcome.status)
                        continue
                    if not extraction.verified:
                        outcome = SourceOutcome(
                            mission.id,
                            source.id,
                            source.adapter,
                            source.visibility,
                            "ERROR",
                            0,
                            (),
                            "extraction verification failed",
                        )
                        source_outcomes.append(outcome)
                        emit("source_failed", mission.id, source.id, outcome.status)
                        continue
                receipt_digests = _persist_source(
                    corpus,
                    source,
                    captured.items,
                    captured.extra_receipts,
                    at=float(clock()),
                )
                status = "CAPTURED" if captured.items else "EMPTY"
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    status,
                    len(captured.items),
                    receipt_digests,
                    "" if status == "CAPTURED" else "source produced no items",
                )
                source_outcomes.append(outcome)
                emit("source_completed", mission.id, source.id, status)
            except _WitnessWriteError as exc:
                witnesses_complete = False
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    "ERROR",
                    0,
                    (),
                    _diagnostic(exc, manifest.policy.credentials),
                )
                source_outcomes.append(outcome)
                emit("source_failed", mission.id, source.id, outcome.status)
            except AdapterUnavailable as exc:
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    "UNAVAILABLE",
                    0,
                    (),
                    _diagnostic(exc, manifest.policy.credentials),
                )
                source_outcomes.append(outcome)
                emit("source_failed", mission.id, source.id, outcome.status)
            except PilotRefusal as exc:
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    "REFUSED",
                    0,
                    (),
                    _diagnostic(exc, manifest.policy.credentials),
                )
                source_outcomes.append(outcome)
                emit("source_failed", mission.id, source.id, outcome.status)
            except Exception as exc:  # noqa: BLE001 - source seams must not erase prior evidence
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    "ERROR",
                    0,
                    (),
                    _diagnostic(exc, manifest.policy.credentials),
                )
                source_outcomes.append(outcome)
                emit("source_failed", mission.id, source.id, outcome.status)

    # Reading the run witnesses here ensures a malformed evidence append cannot be reported as sound.
    corpus_verified = witnesses_complete and _corpus_verified(corpus) and _runs_verified(corpus)
    return PilotResult(
        manifest_sha256=manifest_digest(manifest),
        source_outcomes=tuple(source_outcomes),
        extraction_outcomes=tuple(extraction_outcomes),
        corpus_digest=corpus.digest().seal,
        corpus_verified=corpus_verified,
        monitor_report=None,
        monitor_verified=None,
        limitations=LIMITATIONS,
        does_not_prove=DOES_NOT_PROVE,
    )
