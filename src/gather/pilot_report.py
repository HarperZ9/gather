"""Canonical, redacted pilot reports and network-free artifact verification."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, cast

from gather import __version__
from gather.monitor import verify_ledger
from gather.pilot_manifest import ADAPTERS, MONITOR_ADAPTERS, NETWORK_ADAPTERS
from gather.run import RunRecord, verify_record
from gather.store import MATCH, Corpus

if TYPE_CHECKING:
    from gather.pilot import ExtractionOutcome, PilotResult, PilotVerification
    from gather.pilot_manifest import PilotManifest, PilotSource

PILOT_REPORT_SCHEMA = "gather.pilot-report/1"
PILOT_RECEIPT_SCHEMA = "gather.pilot-receipt/1"

_ARTIFACT_PATHS = {
    "manifest": "manifest.json",
    "report_json": "report.json",
    "report_html": "report.html",
    "corpus": "corpus",
    "monitor_state": "monitor-state.json",
}
_RECEIPT_FIELDS = {
    "schema",
    "manifest_sha256",
    "report_json_sha256",
    "report_html_sha256",
    "semantic_report_sha256",
    "corpus_digest",
    "monitor_root_hash",
    "history_count",
    "history_root_hash",
    "gather_version",
    "artifacts",
}


def canonical_json_bytes(value: object) -> bytes:
    """Encode the one accepted JSON representation for pilot control artifacts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    """Replace one artifact with fully flushed bytes, never a partial file."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _source_by_id(manifest: PilotManifest) -> dict[str, PilotSource]:
    return {
        source.id: source
        for mission in manifest.missions
        for source in mission.sources
    }


def _safe_serialized_target(target: str) -> str | None:
    if PurePosixPath(target).is_absolute() or PureWindowsPath(target).is_absolute():
        return None
    return target


def _extraction_payload(
    outcome: ExtractionOutcome,
    *,
    include_private_content: bool,
) -> dict[str, object]:
    fields: list[dict[str, object]] = []
    for raw_field in outcome.fields:
        field: dict[str, object] = {
            "name": raw_field.get("name"),
            "status": raw_field.get("status"),
            "attr": raw_field.get("attr"),
            "many": raw_field.get("many"),
            "required": raw_field.get("required"),
        }
        if include_private_content:
            field["value"] = raw_field.get("value")
        hits: list[dict[str, object]] = []
        raw_hits = raw_field.get("hits", [])
        if isinstance(raw_hits, Sequence) and not isinstance(raw_hits, (str, bytes)):
            for raw_hit in raw_hits:
                if not isinstance(raw_hit, Mapping):
                    continue
                hit: dict[str, object] = {
                    "source_sha256": raw_hit.get("source_sha256"),
                    "value_sha256": raw_hit.get("value_sha256"),
                }
                if include_private_content:
                    hit["value"] = raw_hit.get("value")
                    hit["path"] = raw_hit.get("path")
                hits.append(hit)
        field["hits"] = hits
        fields.append(field)
    return {
        "source_id": outcome.source_id,
        "fields": fields,
        "missing_required": list(outcome.missing_required),
        "verified": outcome.verified,
    }


def _monitoring_payload(result: PilotResult) -> dict[str, object]:
    report = result.monitor_report
    if report is None:
        return {
            "present": False,
            "counts": {},
            "changed_count": 0,
            "failure_count": 0,
            "root_hash": None,
            "verified": result.monitor_verified,
        }
    counts = report.get("counts", {})
    changed = report.get("changed", [])
    errors = report.get("errors", [])
    gone = report.get("gone", [])
    return {
        "present": True,
        "counts": dict(counts) if isinstance(counts, Mapping) else {},
        "changed_count": len(changed) if isinstance(changed, Sequence) else 0,
        "failure_count": (
            (len(errors) if isinstance(errors, Sequence) else 0)
            + (len(gone) if isinstance(gone, Sequence) else 0)
        ),
        "root_hash": report.get("root_hash"),
        "verified": result.monitor_verified,
    }


def report_payload(
    manifest: PilotManifest,
    result: PilotResult,
    *,
    corpus_stats: Mapping[str, object],
    refresh_sequence: int = 0,
    history_count: int = 0,
) -> dict[str, object]:
    """Project a run result into the canonical report privacy boundary."""
    outcomes = {
        (outcome.mission_id, outcome.source_id): outcome
        for outcome in result.source_outcomes
    }
    extractions = {outcome.source_id: outcome for outcome in result.extraction_outcomes}
    missions: list[dict[str, object]] = []
    visibility_counts: dict[str, int] = {}
    extraction_rows: list[dict[str, object]] = []

    for mission in manifest.missions:
        sources: list[dict[str, object]] = []
        status_counts: dict[str, int] = {}
        for source in mission.sources:
            outcome = outcomes.get((mission.id, source.id))
            if outcome is None:
                continue
            status_counts[outcome.status] = status_counts.get(outcome.status, 0) + 1
            visibility_counts[source.visibility] = (
                visibility_counts.get(source.visibility, 0) + outcome.item_count
            )
            source_row: dict[str, object] = {
                "id": source.id,
                "adapter": source.adapter,
                "visibility": source.visibility,
                "required": source.required,
                "status": outcome.status,
                "item_count": outcome.item_count,
                "receipt_digests": list(outcome.receipt_digests),
            }
            may_include = source.visibility != "private" or manifest.policy.report_private_content
            target = _safe_serialized_target(source.target)
            if may_include and target is not None:
                source_row["target"] = target
            extraction = extractions.get(source.id)
            if extraction is not None:
                extraction_rows.append(
                    _extraction_payload(
                        extraction,
                        include_private_content=may_include,
                    )
                )
            sources.append(source_row)
        missions.append(
            {
                "id": mission.id,
                "title": mission.title,
                "status_counts": dict(sorted(status_counts.items())),
                "sources": sources,
            }
        )

    safe_stats = {
        key: corpus_stats[key]
        for key in ("items", "distinct_bodies", "by_kind", "by_method")
        if key in corpus_stats
    }
    safe_stats["by_visibility"] = dict(sorted(visibility_counts.items()))
    payload: dict[str, object] = {
        "schema": PILOT_REPORT_SCHEMA,
        "pilot_id": manifest.pilot_id,
        "title": manifest.title,
        "mode": manifest.mode,
        "deployment": {
            "mode": manifest.deployment.mode,
            "custodian": manifest.deployment.custodian,
        },
        "gather_version": __version__,
        "manifest_digest": result.manifest_sha256,
        "missions": missions,
        "adapter_capabilities": [
            {
                "adapter": adapter,
                "enabled": adapter in manifest.policy.enabled_adapters,
                "network": adapter in NETWORK_ADAPTERS,
                "monitoring": adapter in MONITOR_ADAPTERS,
                "offline_replay": adapter in NETWORK_ADAPTERS,
            }
            for adapter in ADAPTERS
        ],
        "corpus": {
            **safe_stats,
            "digest": result.corpus_digest,
            "verified": result.corpus_verified,
        },
        "monitoring": _monitoring_payload(result),
        "extractions": extraction_rows,
        "refresh_sequence": refresh_sequence,
        "history_count": history_count,
        "limitations": list(result.limitations),
        "does_not_prove": list(result.does_not_prove),
    }
    payload["report_digest"] = sha256_bytes(canonical_json_bytes(payload))
    return payload


def _escaped(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return escape(str(value), quote=True)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def render_report_html(report: Mapping[str, object]) -> str:
    """Render a self-contained semantic view without active or remote content."""
    title = _escaped(report.get("title", "Gather pilot evidence report"))
    deployment = _mapping(report.get("deployment"))
    corpus = _mapping(report.get("corpus"))
    monitoring = _mapping(report.get("monitoring"))
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{title}</title>",
        "<style>",
        (
            ":root{color-scheme:light dark;font-family:system-ui,sans-serif}"
            "body{max-width:72rem;margin:auto;padding:2rem;line-height:1.5}"
            "table{border-collapse:collapse;width:100%;margin:1rem 0}"
            "th,td{border:1px solid currentColor;padding:.45rem;text-align:left}"
            ".pass{color:#16803a}.fail{color:#b42318}.muted{opacity:.75}"
            "code{font-family:ui-monospace,monospace;overflow-wrap:anywhere}"
            "@media print{body{max-width:none;padding:0}.pass,.fail{color:#000}}"
        ),
        "</style></head><body>",
        f"<header><h1>{title}</h1><p class=\"muted\">Canonical pilot evidence view</p></header>",
        "<main><section><h2>Identity</h2><dl>",
        f"<dt>Pilot</dt><dd>{_escaped(report.get('pilot_id'))}</dd>",
        f"<dt>Mode</dt><dd>{_escaped(report.get('mode'))}</dd>",
        f"<dt>Deployment</dt><dd>{_escaped(deployment.get('mode'))}</dd>",
        f"<dt>Custodian</dt><dd>{_escaped(deployment.get('custodian'))}</dd>",
        f"<dt>Gather version</dt><dd>{_escaped(report.get('gather_version'))}</dd>",
        f"<dt>Manifest digest</dt><dd><code>{_escaped(report.get('manifest_digest'))}</code></dd>",
        f"<dt>Report digest</dt><dd><code>{_escaped(report.get('report_digest'))}</code></dd>",
        "</dl></section>",
    ]
    for mission_value in _rows(report.get("missions")):
        mission = _mapping(mission_value)
        parts.extend(
            [
                f"<section><h2>{_escaped(mission.get('title', mission.get('id')))}</h2>",
                "<table><thead><tr><th>Source</th><th>Adapter</th><th>Visibility</th>"
                "<th>Status</th><th>Items</th></tr></thead><tbody>",
            ]
        )
        for source_value in _rows(mission.get("sources")):
            source = _mapping(source_value)
            status = str(source.get("status", ""))
            css_class = "pass" if status in {"CAPTURED", "EMPTY"} else "fail"
            parts.append(
                "<tr>"
                f"<td>{_escaped(source.get('id'))}</td>"
                f"<td>{_escaped(source.get('adapter'))}</td>"
                f"<td>{_escaped(source.get('visibility'))}</td>"
                f'<td class="{css_class}">{_escaped(status)}</td>'
                f"<td>{_escaped(source.get('item_count'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></section>")
    corpus_class = "pass" if corpus.get("verified") is True else "fail"
    parts.extend(
        [
            "<section><h2>Corpus</h2><dl>",
            f"<dt>Items</dt><dd>{_escaped(corpus.get('items'))}</dd>",
            f"<dt>Distinct bodies</dt><dd>{_escaped(corpus.get('distinct_bodies'))}</dd>",
            f'<dt>Verification</dt><dd class="{corpus_class}">'
            f"{_escaped(corpus.get('verified'))}</dd>",
            f"<dt>Digest</dt><dd><code>{_escaped(corpus.get('digest'))}</code></dd>",
            "</dl></section>",
            "<section><h2>Monitoring</h2><dl>",
            f"<dt>Present</dt><dd>{_escaped(monitoring.get('present'))}</dd>",
            f"<dt>Changes</dt><dd>{_escaped(monitoring.get('changed_count'))}</dd>",
            f"<dt>Failures</dt><dd>{_escaped(monitoring.get('failure_count'))}</dd>",
            f"<dt>Root hash</dt><dd><code>{_escaped(monitoring.get('root_hash'))}</code></dd>",
            "</dl></section>",
            "<section><h2>Limitations</h2><ul>",
        ]
    )
    parts.extend(f"<li>{_escaped(value)}</li>" for value in _rows(report.get("limitations")))
    parts.extend(["</ul></section>", "<section><h2>Does not prove</h2><ul>"])
    parts.extend(f"<li>{_escaped(value)}</li>" for value in _rows(report.get("does_not_prove")))
    parts.extend(
        [
            "</ul><p>These artifacts preserve captured evidence and integrity checks. "
            "They do not establish the truth or completeness of source claims.</p>",
            "</section></main></body></html>",
        ]
    )
    return "".join(parts)


def history_root(receipts: Path | Iterable[bytes]) -> str:
    """Fold archived receipt bytes in sequence order into one chain root."""
    bodies: Iterable[bytes]
    if isinstance(receipts, Path):
        bodies = (
            path.read_bytes()
            for path in sorted(receipts.glob("*-pilot-receipt.json"))
        )
    else:
        bodies = receipts
    previous = ""
    for body in bodies:
        previous = hashlib.sha256(
            (previous + sha256_bytes(body)).encode("ascii")
        ).hexdigest()
    return previous


def build_pilot_receipt(
    root: Path,
    report: Mapping[str, object],
) -> dict[str, object]:
    corpus = _mapping(report.get("corpus"))
    monitoring = _mapping(report.get("monitoring"))
    return {
        "schema": PILOT_RECEIPT_SCHEMA,
        "manifest_sha256": sha256_bytes((root / "manifest.json").read_bytes()),
        "report_json_sha256": sha256_bytes((root / "report.json").read_bytes()),
        "report_html_sha256": sha256_bytes((root / "report.html").read_bytes()),
        "semantic_report_sha256": report["report_digest"],
        "corpus_digest": corpus.get("digest"),
        "monitor_root_hash": monitoring.get("root_hash"),
        "history_count": report["history_count"],
        "history_root_hash": history_root(root / "history"),
        "gather_version": __version__,
        "artifacts": dict(_ARTIFACT_PATHS),
    }


def write_pilot_artifacts(
    root: Path,
    manifest: PilotManifest,
    result: PilotResult,
    *,
    refresh_sequence: int = 0,
    history_count: int = 0,
) -> dict[str, object]:
    """Write report JSON, HTML, and receipt in their required order."""
    corpus = Corpus(str(root / "corpus"))
    report = report_payload(
        manifest,
        result,
        corpus_stats=corpus.stats(),
        refresh_sequence=refresh_sequence,
        history_count=history_count,
    )
    atomic_write_bytes(root / "report.json", canonical_json_bytes(report))
    atomic_write_bytes(root / "report.html", render_report_html(report).encode("utf-8"))
    receipt = build_pilot_receipt(root, report)
    atomic_write_bytes(root / "pilot-receipt.json", canonical_json_bytes(receipt))
    return report


def _read_json_object(path: Path) -> tuple[dict[str, object] | None, bytes | None, bool]:
    try:
        body = path.read_bytes()
        value = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, False
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None, body, False
    typed = cast(dict[str, object], value)
    return typed, body, body == canonical_json_bytes(typed)


def _safe_relative_artifact(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and ".." not in posix.parts
        and ".." not in windows.parts
        and "\\" not in value
    )


def _semantic_report_verified(report: Mapping[str, object]) -> bool:
    digest = report.get("report_digest")
    if not isinstance(digest, str):
        return False
    semantic = dict(report)
    semantic.pop("report_digest", None)
    return digest == sha256_bytes(canonical_json_bytes(semantic))


def _report_manifest_consistent(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
) -> bool:
    if (
        report.get("pilot_id") != manifest.get("pilot_id")
        or report.get("title") != manifest.get("title")
        or report.get("mode") != manifest.get("mode")
        or report.get("deployment") != manifest.get("deployment")
    ):
        return False
    manifest_missions = _rows(manifest.get("missions"))
    report_missions = _rows(report.get("missions"))
    if len(manifest_missions) != len(report_missions):
        return False
    for manifest_value, report_value in zip(manifest_missions, report_missions, strict=True):
        manifest_mission = _mapping(manifest_value)
        report_mission = _mapping(report_value)
        if (
            report_mission.get("id") != manifest_mission.get("id")
            or report_mission.get("title") != manifest_mission.get("title")
        ):
            return False
        manifest_sources = _rows(manifest_mission.get("sources"))
        report_sources = _rows(report_mission.get("sources"))
        if len(manifest_sources) != len(report_sources):
            return False
        for manifest_source_value, report_source_value in zip(
            manifest_sources, report_sources, strict=True
        ):
            manifest_source = _mapping(manifest_source_value)
            report_source = _mapping(report_source_value)
            for key in ("id", "adapter", "visibility", "required"):
                if report_source.get(key) != manifest_source.get(key):
                    return False
    return True


def _source_witness_count(report: Mapping[str, object]) -> int:
    count = 0
    for mission_value in _rows(report.get("missions")):
        mission = _mapping(mission_value)
        for source_value in _rows(mission.get("sources")):
            source = _mapping(source_value)
            if source.get("status") in {"CAPTURED", "EMPTY"}:
                count += 1
    return count


def _corpus_integrity(
    root: Path,
    report: Mapping[str, object],
    receipt: Mapping[str, object],
) -> tuple[bool, str | None]:
    corpus = Corpus(str(root / "corpus"))
    try:
        rows_ok = all(row.get("status") == MATCH for row in corpus.verify())
        witnesses = list(corpus.runs())
        runs_ok = (
            len(witnesses) == _source_witness_count(report)
            and all(verify_record(RunRecord.from_dict(row)) for row in witnesses)
        )
        orphans_ok = not corpus.orphan_objects()
        digest = corpus.digest().seal
    except (OSError, ValueError, TypeError, KeyError):
        return False, None
    report_corpus = _mapping(report.get("corpus"))
    bound = (
        digest == report_corpus.get("digest")
        and digest == receipt.get("corpus_digest")
        and report_corpus.get("verified") is True
    )
    return rows_ok and runs_ok and orphans_ok and bound, digest


def _monitor_integrity(
    root: Path,
    report: Mapping[str, object],
    receipt: Mapping[str, object],
) -> tuple[bool | None, bool]:
    path = root / "monitor-state.json"
    report_monitor = _mapping(report.get("monitoring"))
    present = report_monitor.get("present") is True
    if not path.exists():
        expected_absent = not present and report_monitor.get("root_hash") is None
        return None, expected_absent and receipt.get("monitor_root_hash") is None
    state, _body, _canonical = _read_json_object(path)
    if state is None:
        return (False if present else None), False
    try:
        ledger_ok = verify_ledger(state)
    except (KeyError, TypeError, ValueError):
        ledger_ok = False
    root_hash = state.get("root_hash")
    expected_root = report_monitor.get("root_hash")
    if not present:
        empty_ok = root_hash == "" and state.get("ledger") == []
        binding_ok = expected_root is None and receipt.get("monitor_root_hash") is None
        return None, ledger_ok and empty_ok and binding_ok
    binding_ok = root_hash == expected_root == receipt.get("monitor_root_hash")
    report_verdict = report_monitor.get("verified")
    return ledger_ok and binding_ok and report_verdict is True, binding_ok


def _archived_receipt_ok(
    history: Path,
    sequence: int,
    receipt_body: bytes,
) -> bool:
    prefix = f"{sequence:04d}"
    receipt, _body, canonical = _read_json_object(
        history / f"{prefix}-pilot-receipt.json"
    )
    report, report_body, report_canonical = _read_json_object(
        history / f"{prefix}-report.json"
    )
    try:
        html_body = (history / f"{prefix}-report.html").read_bytes()
    except OSError:
        return False
    if (
        receipt is None
        or report is None
        or report_body is None
        or not canonical
        or not report_canonical
        or receipt_body != canonical_json_bytes(receipt)
    ):
        return False
    return (
        receipt.get("schema") == PILOT_RECEIPT_SCHEMA
        and report.get("schema") == PILOT_REPORT_SCHEMA
        and _semantic_report_verified(report)
        and receipt.get("report_json_sha256") == sha256_bytes(report_body)
        and receipt.get("report_html_sha256") == sha256_bytes(html_body)
        and receipt.get("semantic_report_sha256") == report.get("report_digest")
    )


def _history_integrity(
    root: Path,
    report: Mapping[str, object],
    receipt: Mapping[str, object],
) -> bool:
    report_count = report.get("history_count")
    receipt_count = receipt.get("history_count")
    if (
        not isinstance(report_count, int)
        or isinstance(report_count, bool)
        or report_count < 0
        or receipt_count != report_count
    ):
        return False
    history = root / "history"
    if not history.is_dir():
        return False
    expected = {
        f"{sequence:04d}-{name}"
        for sequence in range(1, report_count + 1)
        for name in ("pilot-receipt.json", "report.html", "report.json")
    }
    try:
        members = {path.name for path in history.iterdir()}
    except OSError:
        return False
    if members != expected:
        return False
    receipt_bodies: list[bytes] = []
    for sequence in range(1, report_count + 1):
        try:
            body = (history / f"{sequence:04d}-pilot-receipt.json").read_bytes()
        except OSError:
            return False
        if not _archived_receipt_ok(history, sequence, body):
            return False
        receipt_bodies.append(body)
    return receipt.get("history_root_hash") == history_root(receipt_bodies)


def verify_pilot(output_dir: Path) -> PilotVerification:
    """Verify a pilot root using local bytes only; malformed evidence returns false."""
    from gather.pilot import PilotVerification

    root = Path(output_dir)
    manifest, manifest_body, manifest_canonical = _read_json_object(root / "manifest.json")
    report, report_body, report_canonical = _read_json_object(root / "report.json")
    receipt, receipt_body, receipt_canonical = _read_json_object(
        root / "pilot-receipt.json"
    )
    try:
        html_body = (root / "report.html").read_bytes()
    except OSError:
        html_body = None

    if receipt is None:
        return PilotVerification(False, False, False, False, None, False)

    artifacts = receipt.get("artifacts")
    paths_valid = (
        isinstance(artifacts, Mapping)
        and dict(artifacts) == _ARTIFACT_PATHS
        and all(_safe_relative_artifact(value) for value in artifacts.values())
    )
    manifest_verified = (
        manifest is not None
        and manifest_body is not None
        and manifest_canonical
        and manifest.get("schema") == "gather.pilot-manifest/1"
        and receipt.get("manifest_sha256") == sha256_bytes(manifest_body)
    )
    report_verified = (
        report is not None
        and report_body is not None
        and manifest is not None
        and report_canonical
        and report.get("schema") == PILOT_REPORT_SCHEMA
        and _semantic_report_verified(report)
        and _report_manifest_consistent(manifest, report)
        and receipt.get("report_json_sha256") == sha256_bytes(report_body)
        and receipt.get("semantic_report_sha256") == report.get("report_digest")
        and report.get("manifest_digest") == receipt.get("manifest_sha256")
        and report.get("gather_version") == __version__
    )
    html_verified = (
        html_body is not None
        and report is not None
        and receipt.get("report_html_sha256") == sha256_bytes(html_body)
        and html_body == render_report_html(report).encode("utf-8")
    )
    corpus_verified = False
    monitor_verified: bool | None = None
    history_verified = False
    monitor_binding = False
    if report is not None:
        corpus_verified, _digest = _corpus_integrity(root, report, receipt)
        monitor_verified, monitor_binding = _monitor_integrity(root, report, receipt)
        history_verified = _history_integrity(root, report, receipt)
    receipt_verified = (
        receipt_canonical
        and receipt_body is not None
        and set(receipt) == _RECEIPT_FIELDS
        and receipt.get("schema") == PILOT_RECEIPT_SCHEMA
        and receipt.get("gather_version") == __version__
        and paths_valid
        and manifest_verified
        and report_verified
        and html_verified
        and monitor_binding
        and history_verified
    )
    return PilotVerification(
        manifest_verified,
        report_verified,
        html_verified,
        corpus_verified,
        monitor_verified,
        receipt_verified,
    )
