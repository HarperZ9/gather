"""Source-isolated execution for closed Gather pilot manifests.

This module owns the durable evidence boundary before reports or monitoring are
rendered.  It deliberately composes the validated manifest, adapter registry,
content-addressed corpus, receipt digest, schema extraction, and run witness.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from gather.digest import digest_of_receipts
from gather.item import Item
from gather.pilot_manifest import (
    PilotManifest,
    PilotSource,
    manifest_digest,
    manifest_payload,
)
from gather.pilot_sources import (
    AdapterUnavailable,
    CapturedSource,
    _fixture_for,
    capture_source,
)
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
    prior_count: int = 0,
) -> tuple[str, ...]:
    receipts = [_item_receipt(item) for item in items] + [dict(receipt) for receipt in extra_receipts]
    digest = digest_of_receipts(receipts)
    stored = corpus.add(list(items))
    origins = tuple(digest.receipts)
    # The witness records THIS run's items honestly: kept/total is the per-run
    # count, added is the new delta. Cumulative accounting across a source's
    # refresh history is validated at the report level from stored.added sums.
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


def _prior_source_count(corpus: Corpus, source: PilotSource) -> int:
    """The cumulative item count recorded for this source in its latest witness.

    A refresh builds on the prior running total rather than re-deriving it from
    corpus rows, so an item whose provenance ref differs from the manifest target
    is still counted honestly by the witness that already vouched for it.
    """
    try:
        target = ((source.adapter, source.target),)
        latest = 0
        for raw in corpus.runs():
            record = RunRecord.from_dict(raw)
            if record.targets == target and isinstance(record.stored, Mapping):
                total = record.stored.get("total")
                if isinstance(total, int):
                    latest = total
        return latest
    except (OSError, ValueError, TypeError, KeyError):
        return 0


def _cumulative_receipt_digests(
    corpus: Corpus, source: PilotSource, new_digests: tuple[str, ...]
) -> tuple[str, ...]:
    """All distinct item-receipt digests vouched for this source across its runs.

    The report row carries the cumulative receipt set so each historical witness
    is a subset of it, while the latest run's new digests are appended on top.
    """
    target = ((source.adapter, source.target),)
    collected: list[str] = []
    seen: set[str] = set()
    try:
        for raw in corpus.runs():
            record = RunRecord.from_dict(raw)
            if record.targets != target:
                continue
            for origin in record.origins:
                sha = origin.get("sha256")
                if isinstance(sha, str) and sha not in seen:
                    seen.add(sha)
                    collected.append(sha)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    for sha in new_digests:
        if sha not in seen:
            seen.add(sha)
            collected.append(sha)
    return tuple(collected)


def _runs_verified(corpus: Corpus) -> bool:
    try:
        return all(verify_record(RunRecord.from_dict(row)) for row in corpus.runs())
    except (OSError, ValueError, TypeError):
        return False


def _monitored_sources(manifest: PilotManifest) -> list[PilotSource]:
    return [
        source
        for mission in manifest.missions
        for source in mission.sources
        if source.monitor
    ]


def _monitor_fetch_fn(manifest: PilotManifest, *, refresh: bool) -> Callable[..., tuple[object, bytes | None]]:
    """Build the fetch function monitor_pass calls for each monitored source.

    Offline monitoring never opens a socket: the body it hashes is the fixture
    file that represents the HTTP response. The receipt carries the content
    digest monitor_pass compares against the prior baseline.
    """
    by_target = {source.target: source for source in _monitored_sources(manifest)}

    def fetch(url: str, etag: str | None = None, last_modified: str | None = None) -> tuple[object, bytes | None]:
        source = by_target.get(url)
        if source is None:
            raise ValueError(f"monitored source not found for {url}")
        body = _fixture_for(source, refresh=refresh).read_bytes()
        receipt = SimpleNamespace(
            status=200,
            not_modified=False,
            content_sha256=hashlib.sha256(body).hexdigest(),
        )
        return receipt, body

    return fetch


def _run_monitor_pass(
    manifest: PilotManifest,
    state: dict[str, object],
    *,
    clock: Callable[[], float],
    refresh: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    """One monitor_pass over the manifest's monitored sources.

    Returns (report, new_state). A manifest with no monitored sources leaves
    the report absent (the run is not a monitoring run).
    """
    from gather.monitor import monitor_pass, verify_ledger

    sources = _monitored_sources(manifest)
    if not sources:
        return {}, state
    report, new_state = monitor_pass(
        [source.target for source in sources],
        state,
        _monitor_fetch_fn(manifest, refresh=refresh),
        clock=clock,
    )
    if not verify_ledger(new_state):
        raise PilotRefusal("monitor ledger failed to verify after the pass")
    # monitor_pass leaves the chain root on the state, not the report; carry it
    # onto the report so the report projection and receipt can bind to it.
    report["root_hash"] = new_state.get("root_hash", "")
    return report, new_state


def _monitor_verified(state: dict[str, object]) -> bool | None:
    from gather.monitor import verify_ledger

    if not state.get("ledger"):
        return None
    try:
        return verify_ledger(state)
    except (KeyError, TypeError, ValueError):
        return False


def _write_monitor_state(root: Path, state: dict[str, object]) -> None:
    _atomic_json(root / "monitor-state.json", state)


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
    monitor_state = json.loads((root / "monitor-state.json").read_text(encoding="utf-8"))
    monitor_report, monitor_state = _run_monitor_pass(
        manifest, monitor_state, clock=clock, refresh=False
    )
    if monitor_report:
        _write_monitor_state(root, monitor_state)
        emit("monitor_completed", None, None, "MONITORED")
    result = PilotResult(
        manifest_sha256=manifest_digest(manifest),
        source_outcomes=tuple(source_outcomes),
        extraction_outcomes=tuple(extraction_outcomes),
        corpus_digest=corpus.digest().seal,
        corpus_verified=corpus_verified,
        monitor_report=monitor_report or None,
        monitor_verified=_monitor_verified(monitor_state) if monitor_report else None,
        limitations=LIMITATIONS,
        does_not_prove=DOES_NOT_PROVE,
    )
    from gather.pilot_report import write_pilot_artifacts

    write_pilot_artifacts(root, manifest, result)
    emit("report_written", None, None, "WRITTEN")
    emit("run_completed", None, None, "COMPLETED")
    return result


def verify_pilot(output_dir: Path) -> PilotVerification:
    """Verify the complete pilot artifact root without network access."""
    from gather.pilot_report import verify_pilot as verify_report

    return verify_report(Path(output_dir))


def _history_count_of(root: Path) -> int:
    """The current history generation: the count of archived receipt triplets."""
    history = root / "history"
    if not history.is_dir():
        return 0
    return sum(1 for path in history.glob("*-pilot-receipt.json"))


def _archive_current(root: Path, sequence: int) -> None:
    """Copy the current report/receipt triplet into history under the next sequence."""
    prefix = f"{sequence:04d}"
    history = root / "history"
    history.mkdir(exist_ok=True)
    for name in ("report.json", "report.html", "pilot-receipt.json"):
        source = root / name
        (history / f"{prefix}-{name}").write_bytes(source.read_bytes())


def refresh_pilot(
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.time,
    event_sink: PilotEventSink | None = None,
) -> PilotResult:
    """Re-capture monitored sources, archive the prior view, and re-verify.

    Accepts no manifest or policy override: the pilot is reconstructed solely
    from ``manifest.json`` inside the artifact root. Refuses before any capture
    or current-file change when the current root does not verify.
    """
    from gather.pilot_manifest import load_pilot_manifest

    root = Path(output_dir)
    if not verify_pilot(root).ok:
        raise PilotRefusal("pilot root does not verify; refusing refresh")

    manifest = load_pilot_manifest(root / "manifest.json")
    corpus = Corpus(str(root / "corpus"))
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

    prior_count = _history_count_of(root)
    _archive_current(root, prior_count + 1)

    source_outcomes: list[SourceOutcome] = []
    for mission in manifest.missions:
        for source in mission.sources:
            if not source.monitor:
                continue
            emit("source_started", mission.id, source.id, "STARTED")
            try:
                captured = capture_source(source, manifest, clock=clock, refresh=True)
                prior = _prior_source_count(corpus, source)
                new_digests = _persist_source(
                    corpus,
                    source,
                    captured.items,
                    captured.extra_receipts,
                    at=float(clock()),
                    prior_count=prior,
                )
                cumulative_digests = _cumulative_receipt_digests(corpus, source, new_digests)
                status = "CAPTURED" if captured.items else "EMPTY"
                outcome = SourceOutcome(
                    mission.id,
                    source.id,
                    source.adapter,
                    source.visibility,
                    status,
                    prior + (1 if captured.items else 0),
                    cumulative_digests,
                    "" if status == "CAPTURED" else "source produced no items",
                )
                source_outcomes.append(outcome)
                emit("source_completed", mission.id, source.id, status)
            except Exception as exc:  # noqa: BLE001 - a refresh source failure must not erase the archive
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

    monitor_state = json.loads((root / "monitor-state.json").read_text(encoding="utf-8"))
    monitor_report, monitor_state = _run_monitor_pass(
        manifest, monitor_state, clock=clock, refresh=True
    )
    if monitor_report:
        _write_monitor_state(root, monitor_state)
        emit("monitor_completed", None, None, "MONITORED")

    new_count = prior_count + 1
    result = PilotResult(
        manifest_sha256=manifest_digest(manifest),
        source_outcomes=tuple(source_outcomes),
        extraction_outcomes=(),
        corpus_digest=corpus.digest().seal,
        corpus_verified=_corpus_verified(corpus) and _runs_verified(corpus),
        monitor_report=monitor_report or None,
        monitor_verified=_monitor_verified(monitor_state) if monitor_report else None,
        limitations=LIMITATIONS,
        does_not_prove=DOES_NOT_PROVE,
    )
    from gather.pilot_report import write_pilot_artifacts

    write_pilot_artifacts(
        root, manifest, result, refresh_sequence=new_count, history_count=new_count
    )
    emit("report_written", None, None, "WRITTEN")
    emit("run_completed", None, None, "COMPLETED")
    return result
