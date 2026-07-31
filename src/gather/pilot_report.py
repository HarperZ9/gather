"""Canonical, redacted pilot reports and network-free artifact verification."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, cast

from gather import __version__
from gather.digest import digest_of_receipts
from gather.monitor import VERDICTS, verify_ledger
from gather.pilot_manifest import (
    ADAPTER_OPTIONS,
    ADAPTERS,
    MONITOR_ADAPTERS,
    NETWORK_ADAPTERS,
    PILOT_MANIFEST_SCHEMA,
    PROVIDER_HOSTS,
)
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
_REPORT_FIELDS = {
    "schema",
    "pilot_id",
    "title",
    "mode",
    "deployment",
    "gather_version",
    "manifest_digest",
    "missions",
    "adapter_capabilities",
    "corpus",
    "monitoring",
    "extractions",
    "refresh_sequence",
    "history_count",
    "limitations",
    "does_not_prove",
    "report_digest",
}
_MISSION_FIELDS = {"id", "title", "status_counts", "sources"}
_SOURCE_FIELDS = {
    "id",
    "adapter",
    "visibility",
    "required",
    "status",
    "item_count",
    "receipt_digests",
}
_CAPABILITY_FIELDS = {
    "adapter",
    "enabled",
    "network",
    "monitoring",
    "offline_replay",
}
_CORPUS_FIELDS = {
    "items",
    "distinct_bodies",
    "by_kind",
    "by_method",
    "by_visibility",
    "digest",
    "verified",
}
_MONITORING_FIELDS = {
    "present",
    "counts",
    "changed_count",
    "failure_count",
    "root_hash",
    "verified",
}
_EXTRACTION_FIELDS = {"source_id", "fields", "missing_required", "verified"}
_FIELD_FIELDS = {"name", "status", "attr", "many", "required", "hits"}
_HIT_FIELDS = {"source_sha256", "value_sha256"}
_SOURCE_STATUSES = frozenset(
    {"CAPTURED", "EMPTY", "UNAVAILABLE", "REFUSED", "ERROR"}
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]*\Z")
_CREDENTIAL = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


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
            may_include = source.visibility != "private"
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


def _exact_fields(value: Mapping[str, object], fields: set[str]) -> bool:
    return set(value) == fields


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _digest(value: object, *, allow_empty: bool = False) -> bool:
    return (allow_empty and value == "") or (
        isinstance(value, str) and _HEX64.fullmatch(value) is not None
    )


def _string_list(
    value: object,
    *,
    nonempty: bool = False,
    unique: bool = False,
    sorted_values: bool = False,
) -> bool:
    if not isinstance(value, list) or not all(_nonempty_string(item) for item in value):
        return False
    typed = cast(list[str], value)
    return (
        (not nonempty or bool(typed))
        and (not unique or len(set(typed)) == len(typed))
        and (not sorted_values or typed == sorted(typed))
    )


def _counts(value: object, *, allowed: set[str] | None = None) -> bool:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        return False
    if allowed is not None and not set(value).issubset(allowed):
        return False
    return all(_integer(count) for count in value.values())


def _json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return all(_json_value(item) for item in value.values())
    return False


def _portable_relative(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and _safe_relative_artifact(value)
        and PurePosixPath(value).as_posix() == value
    )


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _valid_extraction_schema(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping) or set(value) != {"fields"}:
        return False
    fields = value.get("fields")
    if not isinstance(fields, Mapping) or not all(
        isinstance(name, str) and _SLUG.fullmatch(name) is not None
        for name in fields
    ):
        return False
    for spec_value in fields.values():
        if not isinstance(spec_value, Mapping) or set(spec_value) != {
            "selector",
            "attr",
            "regex",
            "many",
            "required",
        }:
            return False
        if (
            not _nonempty_string(spec_value.get("selector"))
            or (
                spec_value.get("attr") is not None
                and not _nonempty_string(spec_value.get("attr"))
            )
            or (
                spec_value.get("regex") is not None
                and not _nonempty_string(spec_value.get("regex"))
            )
            or not isinstance(spec_value.get("many"), bool)
            or not isinstance(spec_value.get("required"), bool)
        ):
            return False
    return True


def _valid_normalized_manifest(manifest: Mapping[str, object]) -> bool:
    if not _exact_fields(
        manifest,
        {"schema", "pilot_id", "title", "mode", "deployment", "policy", "missions"},
    ):
        return False
    if (
        manifest.get("schema") != PILOT_MANIFEST_SCHEMA
        or not isinstance(manifest.get("pilot_id"), str)
        or _SLUG.fullmatch(cast(str, manifest.get("pilot_id"))) is None
        or not _nonempty_string(manifest.get("title"))
        or manifest.get("mode") not in {"offline", "live"}
    ):
        return False
    deployment = manifest.get("deployment")
    if (
        not isinstance(deployment, Mapping)
        or set(deployment) != {"mode", "custodian"}
        or deployment.get("mode")
        not in {"workstation", "customer_hosted", "zentropy_managed"}
        or deployment.get("custodian") not in {"customer", "zentropy", "shared"}
    ):
        return False
    policy = manifest.get("policy")
    if (
        not isinstance(policy, Mapping)
        or set(policy)
        != {
            "allowed_hosts",
            "trusted_browser_hosts",
            "allowed_local_roots",
            "enabled_adapters",
            "credentials",
            "report_private_content",
        }
        or not isinstance(policy.get("report_private_content"), bool)
    ):
        return False
    for key in (
        "allowed_hosts",
        "trusted_browser_hosts",
        "allowed_local_roots",
        "enabled_adapters",
        "credentials",
    ):
        if not _string_list(
            policy.get(key),
            nonempty=key == "enabled_adapters",
            unique=True,
            sorted_values=True,
        ):
            return False
    allowed_hosts = cast(list[str], policy.get("allowed_hosts"))
    trusted_hosts = cast(list[str], policy.get("trusted_browser_hosts"))
    roots = cast(list[str], policy.get("allowed_local_roots"))
    enabled = cast(list[str], policy.get("enabled_adapters"))
    credentials = cast(list[str], policy.get("credentials"))
    if (
        any(
            host != host.lower()
            or host.endswith(".")
            or "." not in host
            or _is_ip_literal(host)
            or any(
                not part or re.fullmatch(r"[a-z0-9-]+", part) is None
                for part in host.split(".")
            )
            for host in allowed_hosts
        )
        or not set(trusted_hosts).issubset(allowed_hosts)
        or any(not _portable_relative(root) for root in roots)
        or any(adapter not in ADAPTERS for adapter in enabled)
        or any(_CREDENTIAL.fullmatch(name) is None for name in credentials)
    ):
        return False
    missions = manifest.get("missions")
    if not isinstance(missions, list) or not missions:
        return False
    mission_ids: set[str] = set()
    source_ids: set[str] = set()
    mode = cast(str, manifest.get("mode"))
    for mission_value in missions:
        if (
            not isinstance(mission_value, Mapping)
            or set(mission_value) != {"id", "title", "sources"}
        ):
            return False
        mission_id = mission_value.get("id")
        sources = mission_value.get("sources")
        if (
            not isinstance(mission_id, str)
            or _SLUG.fullmatch(mission_id) is None
            or mission_id in mission_ids
            or not _nonempty_string(mission_value.get("title"))
            or not isinstance(sources, list)
            or not sources
        ):
            return False
        mission_ids.add(mission_id)
        for source_value in sources:
            if (
                not isinstance(source_value, Mapping)
                or set(source_value)
                != {
                    "id",
                    "adapter",
                    "target",
                    "fixture",
                    "refresh_fixture",
                    "visibility",
                    "monitor",
                    "required",
                    "extraction",
                    "options",
                }
            ):
                return False
            source_id = source_value.get("id")
            adapter = source_value.get("adapter")
            target = source_value.get("target")
            fixture = source_value.get("fixture")
            refresh_fixture = source_value.get("refresh_fixture")
            monitor = source_value.get("monitor")
            options = source_value.get("options")
            if (
                not isinstance(source_id, str)
                or _SLUG.fullmatch(source_id) is None
                or source_id in source_ids
                or adapter not in enabled
                or not _nonempty_string(target)
                or source_value.get("visibility") not in {"private", "public"}
                or not isinstance(monitor, bool)
                or not isinstance(source_value.get("required"), bool)
                or (fixture is not None and not _portable_relative(fixture))
                or (refresh_fixture is not None and not _portable_relative(refresh_fixture))
                or not _valid_extraction_schema(source_value.get("extraction"))
                or not isinstance(options, Mapping)
                or set(options) - set(ADAPTER_OPTIONS[cast(str, adapter)])
                or not all(_json_value(item) for item in options.values())
            ):
                return False
            source_ids.add(source_id)
            if source_value.get("extraction") is not None and adapter not in {"web", "browser"}:
                return False
            if monitor and adapter not in MONITOR_ADAPTERS:
                return False
            if refresh_fixture is not None and not monitor:
                return False
            if adapter in NETWORK_ADAPTERS:
                parsed = urllib.parse.urlsplit(cast(str, target))
                try:
                    port = parsed.port
                except ValueError:
                    return False
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or port is not None
                    or parsed.netloc != parsed.hostname
                    or parsed.hostname not in allowed_hosts
                    or (
                        adapter in PROVIDER_HOSTS
                        and parsed.hostname not in PROVIDER_HOSTS[cast(str, adapter)]
                    )
                    or (
                        adapter == "browser"
                        and parsed.hostname not in trusted_hosts
                    )
                    or (mode == "offline" and fixture is None)
                    or (mode == "live" and fixture is not None)
                    or (mode == "live" and refresh_fixture is not None)
                ):
                    return False
            elif not _portable_relative(target) or (mode == "live" and fixture is not None):
                return False
    return True


def _valid_report_extractions(
    report: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    source_specs: dict[str, Mapping[str, object]] = {}
    source_order: dict[str, int] = {}
    position = 0
    for mission_value in _rows(manifest.get("missions")):
        mission = _mapping(mission_value)
        for source_value in _rows(mission.get("sources")):
            source = _mapping(source_value)
            source_id = source.get("id")
            if isinstance(source_id, str):
                source_specs[source_id] = source
                source_order[source_id] = position
                position += 1
    values = report.get("extractions")
    if not isinstance(values, list):
        return False
    seen: set[str] = set()
    ordered: list[int] = []
    for extraction_value in values:
        if (
            not isinstance(extraction_value, Mapping)
            or set(extraction_value) != _EXTRACTION_FIELDS
        ):
            return False
        source_id = extraction_value.get("source_id")
        fields = extraction_value.get("fields")
        missing = extraction_value.get("missing_required")
        extraction_source = source_specs.get(cast(str, source_id))
        schema = (
            _mapping(extraction_source.get("extraction"))
            if extraction_source is not None
            else {}
        )
        schema_fields = _mapping(schema.get("fields"))
        if (
            not isinstance(source_id, str)
            or source_id in seen
            or extraction_source is None
            or not schema_fields
            or not isinstance(fields, list)
            or not _string_list(missing, unique=True)
            or not isinstance(extraction_value.get("verified"), bool)
        ):
            return False
        seen.add(source_id)
        ordered.append(source_order[source_id])
        field_names: list[str] = []
        expected_missing: list[str] = []
        private = extraction_source.get("visibility") == "private"
        for field_value in fields:
            allowed_field_keys = _FIELD_FIELDS if private else _FIELD_FIELDS | {"value"}
            if (
                not isinstance(field_value, Mapping)
                or set(field_value) != allowed_field_keys
            ):
                return False
            name = field_value.get("name")
            hits = field_value.get("hits")
            spec = _mapping(schema_fields.get(cast(str, name)))
            if (
                not isinstance(name, str)
                or name not in schema_fields
                or name in field_names
                or field_value.get("status") not in {"extracted", "missing"}
                or field_value.get("attr") != spec.get("attr")
                or field_value.get("many") != spec.get("many")
                or field_value.get("required") != spec.get("required")
                or not isinstance(hits, list)
                or field_value.get("status")
                != ("extracted" if hits else "missing")
            ):
                return False
            field_names.append(name)
            if spec.get("required") is True and field_value.get("status") == "missing":
                expected_missing.append(name)
            for hit_value in hits:
                allowed_hit_keys = _HIT_FIELDS if private else _HIT_FIELDS | {"value", "path"}
                if (
                    not isinstance(hit_value, Mapping)
                    or set(hit_value) != allowed_hit_keys
                    or not _digest(hit_value.get("source_sha256"))
                    or not _digest(hit_value.get("value_sha256"))
                    or (
                        not private
                        and (
                            not _nonempty_string(hit_value.get("value"))
                            or not _nonempty_string(hit_value.get("path"))
                        )
                    )
                ):
                    return False
            if not private:
                hit_values = [
                    _mapping(hit).get("value")
                    for hit in cast(list[object], hits)
                ]
                expected_value: object = (
                    hit_values
                    if spec.get("many") is True
                    else (hit_values[0] if hit_values else None)
                )
                if field_value.get("value") != expected_value:
                    return False
        if set(field_names) != set(schema_fields):
            return False
        if missing != expected_missing:
            return False
    return ordered == sorted(ordered)


def _valid_report(
    report: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    if not _exact_fields(report, _REPORT_FIELDS):
        return False
    if (
        report.get("schema") != PILOT_REPORT_SCHEMA
        or report.get("pilot_id") != manifest.get("pilot_id")
        or report.get("title") != manifest.get("title")
        or report.get("mode") != manifest.get("mode")
        or report.get("deployment") != manifest.get("deployment")
        or report.get("gather_version") != __version__
        or not _digest(report.get("manifest_digest"))
        or not _digest(report.get("report_digest"))
        or not _integer(report.get("refresh_sequence"))
        or not _integer(report.get("history_count"))
        or report.get("refresh_sequence") != report.get("history_count")
        or not _string_list(report.get("limitations"))
        or not _string_list(report.get("does_not_prove"))
    ):
        return False
    manifest_policy = _mapping(manifest.get("policy"))
    enabled = set(cast(list[str], manifest_policy.get("enabled_adapters")))
    expected_capabilities = [
        {
            "adapter": adapter,
            "enabled": adapter in enabled,
            "network": adapter in NETWORK_ADAPTERS,
            "monitoring": adapter in MONITOR_ADAPTERS,
            "offline_replay": adapter in NETWORK_ADAPTERS,
        }
        for adapter in ADAPTERS
    ]
    capabilities = report.get("adapter_capabilities")
    if (
        not isinstance(capabilities, list)
        or capabilities != expected_capabilities
        or not all(
            isinstance(item, Mapping) and set(item) == _CAPABILITY_FIELDS
            for item in capabilities
        )
    ):
        return False
    manifest_missions = _rows(manifest.get("missions"))
    report_missions = report.get("missions")
    if not isinstance(report_missions, list) or len(report_missions) != len(manifest_missions):
        return False
    for manifest_value, report_value in zip(
        manifest_missions, report_missions, strict=True
    ):
        manifest_mission = _mapping(manifest_value)
        if not isinstance(report_value, Mapping) or set(report_value) != _MISSION_FIELDS:
            return False
        report_mission = report_value
        if (
            report_mission.get("id") != manifest_mission.get("id")
            or report_mission.get("title") != manifest_mission.get("title")
        ):
            return False
        manifest_sources = _rows(manifest_mission.get("sources"))
        report_sources = report_mission.get("sources")
        if not isinstance(report_sources, list) or len(report_sources) != len(manifest_sources):
            return False
        status_counts: dict[str, int] = {}
        for manifest_source_value, report_source_value in zip(
            manifest_sources, report_sources, strict=True
        ):
            manifest_source = _mapping(manifest_source_value)
            if not isinstance(report_source_value, Mapping):
                return False
            report_source = report_source_value
            private = manifest_source.get("visibility") == "private"
            expected_keys = _SOURCE_FIELDS if private else _SOURCE_FIELDS | {"target"}
            status = report_source.get("status")
            item_count = report_source.get("item_count")
            receipt_digests = report_source.get("receipt_digests")
            if (
                set(report_source) != expected_keys
                or any(
                    report_source.get(key) != manifest_source.get(key)
                    for key in ("id", "adapter", "visibility", "required")
                )
                or (
                    not private
                    and report_source.get("target") != manifest_source.get("target")
                )
                or status not in _SOURCE_STATUSES
                or not _integer(item_count)
                or not isinstance(receipt_digests, list)
                or not all(_digest(value) for value in receipt_digests)
                or (status == "CAPTURED" and cast(int, item_count) == 0)
                or (status == "EMPTY" and cast(int, item_count) != 0)
                or (
                    status in {"UNAVAILABLE", "REFUSED", "ERROR"}
                    and (cast(int, item_count) != 0 or receipt_digests)
                )
            ):
                return False
            status_counts[cast(str, status)] = status_counts.get(cast(str, status), 0) + 1
        if (
            report_mission.get("status_counts")
            != dict(sorted(status_counts.items()))
        ):
            return False
    corpus = report.get("corpus")
    if (
        not isinstance(corpus, Mapping)
        or set(corpus) != _CORPUS_FIELDS
        or not _integer(corpus.get("items"))
        or not _integer(corpus.get("distinct_bodies"))
        or not _counts(corpus.get("by_kind"))
        or not _counts(corpus.get("by_method"))
        or not _counts(corpus.get("by_visibility"), allowed={"private", "public"})
        or not _digest(corpus.get("digest"))
        or not isinstance(corpus.get("verified"), bool)
    ):
        return False
    monitoring = report.get("monitoring")
    if (
        not isinstance(monitoring, Mapping)
        or set(monitoring) != _MONITORING_FIELDS
        or not isinstance(monitoring.get("present"), bool)
        or not _counts(monitoring.get("counts"), allowed=set(VERDICTS))
        or not _integer(monitoring.get("changed_count"))
        or not _integer(monitoring.get("failure_count"))
        or (
            monitoring.get("root_hash") is not None
            and not _digest(monitoring.get("root_hash"), allow_empty=True)
        )
        or monitoring.get("verified") not in {True, False, None}
    ):
        return False
    return _valid_report_extractions(report, manifest)


def _valid_receipt(receipt: Mapping[str, object]) -> bool:
    artifacts = receipt.get("artifacts")
    return (
        _exact_fields(receipt, _RECEIPT_FIELDS)
        and receipt.get("schema") == PILOT_RECEIPT_SCHEMA
        and _digest(receipt.get("manifest_sha256"))
        and _digest(receipt.get("report_json_sha256"))
        and _digest(receipt.get("report_html_sha256"))
        and _digest(receipt.get("semantic_report_sha256"))
        and _digest(receipt.get("corpus_digest"))
        and (
            receipt.get("monitor_root_hash") is None
            or _digest(receipt.get("monitor_root_hash"), allow_empty=True)
        )
        and _integer(receipt.get("history_count"))
        and _digest(receipt.get("history_root_hash"), allow_empty=True)
        and receipt.get("gather_version") == __version__
        and isinstance(artifacts, Mapping)
        and dict(artifacts) == _ARTIFACT_PATHS
        and all(_safe_relative_artifact(value) for value in artifacts.values())
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


def _receipt_identity(receipt: Mapping[str, object]) -> bytes:
    clean = digest_of_receipts([dict(receipt)]).receipts[0]
    return canonical_json_bytes(clean)


def _expected_source_witnesses(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    expected: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for manifest_mission_value, report_mission_value in zip(
        _rows(manifest.get("missions")),
        _rows(report.get("missions")),
        strict=True,
    ):
        manifest_mission = _mapping(manifest_mission_value)
        report_mission = _mapping(report_mission_value)
        for manifest_source_value, report_source_value in zip(
            _rows(manifest_mission.get("sources")),
            _rows(report_mission.get("sources")),
            strict=True,
        ):
            manifest_source = _mapping(manifest_source_value)
            report_source = _mapping(report_source_value)
            if report_source.get("status") in {"CAPTURED", "EMPTY"}:
                expected.append((manifest_source, report_source))
    return expected


def _stored_counts_valid(
    value: object,
    item_count: int,
    expected_added: int,
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"added", "deduped", "total"}:
        return False
    added = value.get("added")
    deduped = value.get("deduped")
    total = value.get("total")
    return (
        _integer(added)
        and _integer(deduped)
        and added == expected_added
        and deduped == item_count - expected_added
        and total == item_count
        and cast(int, added) + cast(int, deduped) == item_count
    )


def _witness_valid(
    raw: Mapping[str, object],
    manifest_source: Mapping[str, object],
    report_source: Mapping[str, object],
    catalog_receipts: set[bytes],
    previously_accounted: set[bytes],
) -> tuple[bool, set[bytes]]:
    item_count = cast(int, report_source.get("item_count"))
    expected_fields = {
        "started_at",
        "targets",
        "scope",
        "gathered",
        "kept",
        "dropped",
        "synthesized",
        "digested",
        "digest_seal",
        "stored",
        "seal",
    }
    if raw.get("origins"):
        expected_fields.add("origins")
    if set(raw) != expected_fields:
        return False, set()
    try:
        record = RunRecord.from_dict(dict(raw))
        origins = [dict(value) for value in record.origins]
        origin_digest = digest_of_receipts(origins)
        item_receipt_list = [
            _receipt_identity(value) for value in origins[:item_count]
        ]
        item_receipts = set(item_receipt_list)
    except (TypeError, ValueError, KeyError):
        return False, set()
    receipt_digests = report_source.get("receipt_digests")
    options = _mapping(manifest_source.get("options"))
    extras = origins[item_count:]
    seen = set(previously_accounted)
    expected_added = 0
    for identity in item_receipt_list:
        if identity not in seen:
            expected_added += 1
            seen.add(identity)
    valid = (
        verify_record(record)
        and _number(record.started_at)
        and record.targets
        == (
            (
                manifest_source.get("adapter"),
                manifest_source.get("target"),
            ),
        )
        and record.scope == ()
        and record.gathered == item_count
        and record.kept == item_count
        and record.dropped == 0
        and record.synthesized is False
        and record.digested == item_count
        and _stored_counts_valid(record.stored, item_count, expected_added)
        and len(origins) >= item_count
        and item_receipts.issubset(catalog_receipts)
        and record.digest_seal == origin_digest.seal
        and isinstance(receipt_digests, list)
        and receipt_digests
        == [receipt.get("sha256") for receipt in origin_digest.receipts]
        and (
            not extras
            or (
                manifest_source.get("adapter") == "scholar"
                and options.get("edges") is True
            )
        )
    )
    return valid, item_receipts


def _corpus_integrity(
    root: Path,
    manifest: Mapping[str, object],
    report: Mapping[str, object],
    receipt: Mapping[str, object],
) -> tuple[bool, str | None]:
    corpus = Corpus(str(root / "corpus"))
    try:
        rows = list(corpus.rows())
        rows_ok = all(row.get("status") == MATCH for row in corpus.verify())
        catalog_receipts = {_receipt_identity(row) for row in rows}
        witnesses = list(corpus.runs())
        expected = _expected_source_witnesses(manifest, report)
        accounted: set[bytes] = set()
        runs_ok = len(witnesses) == len(expected)
        for raw, (manifest_source, report_source) in zip(
            witnesses, expected, strict=True
        ):
            witness_ok, item_receipts = _witness_valid(
                raw,
                manifest_source,
                report_source,
                catalog_receipts,
                accounted,
            )
            runs_ok = runs_ok and witness_ok
            accounted.update(item_receipts)
        runs_ok = runs_ok and catalog_receipts.issubset(accounted)
        orphans_ok = not corpus.orphan_objects()
        digest = corpus.digest().seal
        stats = corpus.stats()
    except (OSError, ValueError, TypeError, KeyError):
        return False, None
    report_corpus = _mapping(report.get("corpus"))
    visibility_counts: dict[str, int] = {}
    for mission_value in _rows(report.get("missions")):
        for source_value in _rows(_mapping(mission_value).get("sources")):
            source = _mapping(source_value)
            visibility = source.get("visibility")
            item_count = source.get("item_count")
            if isinstance(visibility, str) and isinstance(item_count, int):
                visibility_counts[visibility] = (
                    visibility_counts.get(visibility, 0) + item_count
                )
    stats_bound = (
        report_corpus.get("items") == stats.get("items")
        and report_corpus.get("distinct_bodies") == stats.get("distinct_bodies")
        and report_corpus.get("by_kind") == stats.get("by_kind")
        and report_corpus.get("by_method") == stats.get("by_method")
        and report_corpus.get("by_visibility")
        == dict(sorted(visibility_counts.items()))
    )
    bound = (
        digest == report_corpus.get("digest")
        and digest == receipt.get("corpus_digest")
        and report_corpus.get("verified") is True
        and stats_bound
    )
    return rows_ok and runs_ok and orphans_ok and bound, digest


def _monitor_integrity(
    root: Path,
    manifest: Mapping[str, object],
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
    baselines = state.get("baselines")
    ledger = state.get("ledger")
    root_hash = state.get("root_hash")
    state_shape = (
        set(state) == {"schema", "baselines", "ledger", "root_hash"}
        and state.get("schema") == "gather.monitor-state/1"
        and isinstance(baselines, Mapping)
        and isinstance(ledger, list)
        and _digest(root_hash, allow_empty=True)
    )
    if state_shape:
        for baseline_value in cast(Mapping[str, object], baselines).values():
            state_shape = state_shape and (
                isinstance(baseline_value, Mapping)
                and set(baseline_value)
                == {"content_sha256", "fetched_at", "etag", "last_modified"}
                and _digest(baseline_value.get("content_sha256"))
                and _number(baseline_value.get("fetched_at"))
                and isinstance(baseline_value.get("etag"), str)
                and isinstance(baseline_value.get("last_modified"), str)
            )
        for entry_value in cast(list[object], ledger):
            state_shape = state_shape and (
                isinstance(entry_value, Mapping)
                and set(entry_value)
                == {
                    "url",
                    "verdict",
                    "at",
                    "content_sha256",
                    "prev_sha256",
                    "status",
                    "entry_hash",
                }
                and _nonempty_string(entry_value.get("url"))
                and entry_value.get("verdict") in VERDICTS
                and _number(entry_value.get("at"))
                and _digest(entry_value.get("content_sha256"), allow_empty=True)
                and _digest(entry_value.get("prev_sha256"), allow_empty=True)
                and _integer(entry_value.get("status"))
                and _digest(entry_value.get("entry_hash"))
            )
    try:
        ledger_ok = state_shape and verify_ledger(state)
    except (KeyError, TypeError, ValueError):
        ledger_ok = False
    monitored_count = sum(
        1
        for mission_value in _rows(manifest.get("missions"))
        for source_value in _rows(_mapping(mission_value).get("sources"))
        if _mapping(source_value).get("monitor") is True
    )
    if not ledger:
        expected = {
            "present": False,
            "counts": {},
            "changed_count": 0,
            "failure_count": 0,
            "root_hash": None,
            "verified": None,
        }
        binding_ok = (
            report_monitor == expected
            and receipt.get("monitor_root_hash") is None
            and root_hash == ""
            and baselines == {}
        )
        return None, ledger_ok and binding_ok
    if (
        monitored_count <= 0
        or len(cast(list[object], ledger)) < monitored_count
        or len(cast(list[object], ledger)) % monitored_count != 0
    ):
        return False, False
    latest = cast(list[Mapping[str, object]], ledger)[-monitored_count:]
    if len({entry.get("url") for entry in latest}) != monitored_count:
        return False, False
    counts = {verdict: 0 for verdict in VERDICTS}
    for entry in latest:
        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            return False, False
        counts[cast(str, verdict)] += 1
    expected = {
        "present": True,
        "counts": counts,
        "changed_count": counts["CHANGED"],
        "failure_count": counts["GONE"] + counts["ERROR"],
        "root_hash": root_hash,
        "verified": True,
    }
    binding_ok = (
        present
        and report_monitor == expected
        and receipt.get("monitor_root_hash") == root_hash
    )
    return ledger_ok and binding_ok, binding_ok


def _archived_receipt_ok(
    history: Path,
    sequence: int,
    receipt_body: bytes,
    manifest: Mapping[str, object],
    manifest_sha256: str,
    predecessor_root: str,
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
        _valid_receipt(receipt)
        and _valid_report(report, manifest)
        and _semantic_report_verified(report)
        and receipt.get("manifest_sha256") == manifest_sha256
        and receipt.get("report_json_sha256") == sha256_bytes(report_body)
        and receipt.get("report_html_sha256") == sha256_bytes(html_body)
        and receipt.get("semantic_report_sha256") == report.get("report_digest")
        and receipt.get("corpus_digest") == _mapping(report.get("corpus")).get("digest")
        and receipt.get("monitor_root_hash")
        == _mapping(report.get("monitoring")).get("root_hash")
        and receipt.get("history_count") == sequence - 1
        and report.get("history_count") == sequence - 1
        and report.get("refresh_sequence") == sequence - 1
        and receipt.get("history_root_hash") == predecessor_root
        and html_body == render_report_html(report).encode("utf-8")
    )


def _history_integrity(
    root: Path,
    manifest: Mapping[str, object],
    manifest_sha256: str,
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
    previous = ""
    for sequence in range(1, report_count + 1):
        try:
            body = (history / f"{sequence:04d}-pilot-receipt.json").read_bytes()
        except OSError:
            return False
        if not _archived_receipt_ok(
            history,
            sequence,
            body,
            manifest,
            manifest_sha256,
            previous,
        ):
            return False
        previous = hashlib.sha256(
            (previous + sha256_bytes(body)).encode("ascii")
        ).hexdigest()
    return receipt.get("history_root_hash") == previous


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

    receipt_shape = _valid_receipt(receipt)
    manifest_shape = manifest is not None and _valid_normalized_manifest(manifest)
    report_shape = (
        report is not None
        and manifest is not None
        and manifest_shape
        and _valid_report(report, manifest)
    )
    manifest_verified = (
        manifest is not None
        and manifest_body is not None
        and manifest_canonical
        and manifest_shape
        and receipt.get("manifest_sha256") == sha256_bytes(manifest_body)
    )
    report_verified = (
        report is not None
        and report_body is not None
        and manifest is not None
        and report_canonical
        and report_shape
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
    if report is not None and manifest is not None and report_shape:
        corpus_verified, _corpus_digest = _corpus_integrity(
            root,
            manifest,
            report,
            receipt,
        )
        monitor_verified, monitor_binding = _monitor_integrity(
            root,
            manifest,
            report,
            receipt,
        )
        history_verified = (
            manifest_body is not None
            and _history_integrity(
                root,
                manifest,
                sha256_bytes(manifest_body),
                report,
                receipt,
            )
        )
    receipt_verified = (
        receipt_canonical
        and receipt_body is not None
        and receipt_shape
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
