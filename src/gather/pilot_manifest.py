"""Closed, local-only validation for Gather pilot manifests.

Validation is deliberately pure: it resolves declared local files to enforce
the policy boundary, but never fetches a target or reads a credential value.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from gather.schema_extract import Field

ADAPTERS = (
    "web", "feed", "docs", "pdf", "arxiv", "scholar",
    "video", "api", "browser", "ocr", "transcribe",
)
NETWORK_ADAPTERS = ("web", "feed", "arxiv", "scholar", "video", "api", "browser")
MONITOR_ADAPTERS = ("web", "feed", "api")
PILOT_MANIFEST_SCHEMA = "gather.pilot-manifest/1"

PROVIDER_HOSTS = {
    "arxiv": ("export.arxiv.org",),
    "scholar": (
        "api.openalex.org",
        "api.semanticscholar.org",
        "api.crossref.org",
    ),
}

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

_SLUG = re.compile(r"[a-z][a-z0-9-]*\Z")
_CREDENTIAL = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_EXTRACTION_ADAPTERS = frozenset({"web", "browser"})


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


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _closed(data: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} field: {unknown[0]}")


def _string(data: Mapping[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, object], key: str, label: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string or null")
    return value


def _bool(data: Mapping[str, object], key: str, label: str, default: bool | None = None) -> bool:
    if key not in data and default is not None:
        return default
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{label}.{key} must be a boolean")
    return value


def _items(data: Mapping[str, object], key: str, label: str) -> list[object]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label}.{key} must be a list")
    return value


def _slug(value: str, label: str) -> str:
    if _SLUG.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase slug")
    return value


def _credential(value: str) -> str:
    if _CREDENTIAL.fullmatch(value) is None:
        raise ValueError("credential name must be an uppercase environment variable name")
    return value


def _canonical_host(value: str, label: str) -> str:
    if not value or value != value.lower() or value.endswith("."):
        raise ValueError(f"{label} must be a lowercase canonical DNS host")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError(f"{label} may not be an IP literal")
    if "." not in value or any(not part or not re.fullmatch(r"[a-z0-9-]+", part) for part in value.split(".")):
        raise ValueError(f"{label} must be a lowercase canonical DNS host")
    return value


def _network_host(target: str) -> str:
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("network target must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("network target may not contain user information or a port")
    if parsed.netloc != parsed.hostname:
        raise ValueError("network target host must be lowercase and canonical")
    return _canonical_host(parsed.hostname, "network target host")


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve(strict=True)
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)


def _relative_path(value: str, label: str, base_dir: Path, roots: tuple[Path, ...]) -> tuple[str, Path]:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative path inside an allowed local root")
    try:
        resolved = (base_dir / path).resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"{label} must name an existing local file") from error
    if not _inside(resolved, roots):
        raise ValueError(f"{label} must be inside an allowed local root")
    return path.as_posix(), resolved


def _json_value(value: object, label: str) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return tuple(_json_value(item, label) for item in value)
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return MappingProxyType({key: _json_value(item, label) for key, item in value.items()})
    raise ValueError(f"{label} must contain only JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _options(value: object, adapter: str) -> Mapping[str, object]:
    data = _mapping(value, "source.options")
    _closed(data, set(ADAPTER_OPTIONS[adapter]), f"{adapter} options")
    return MappingProxyType({key: _json_value(item, f"source.options.{key}") for key, item in data.items()})


def _extraction(value: object, adapter: str) -> Mapping[str, Field] | None:
    if value is None:
        return None
    if adapter not in _EXTRACTION_ADAPTERS:
        raise ValueError(f"{adapter} does not support extraction")
    data = _mapping(value, "source.extraction")
    _closed(data, {"fields"}, "extraction")
    fields_data = _mapping(data.get("fields"), "source.extraction.fields")
    fields: dict[str, Field] = {}
    for name, raw in fields_data.items():
        if not _SLUG.fullmatch(name):
            raise ValueError("source.extraction field names must be lowercase slugs")
        spec = _mapping(raw, f"source.extraction.{name}")
        _closed(spec, {"selector", "attr", "regex", "many", "required"}, "extraction")
        selector = _string(spec, "selector", f"source.extraction.{name}")
        attr = _optional_string(spec, "attr", f"source.extraction.{name}")
        regex = _optional_string(spec, "regex", f"source.extraction.{name}")
        many = spec.get("many", False)
        required = spec.get("required", True)
        if not isinstance(many, bool) or not isinstance(required, bool):
            raise ValueError(f"source.extraction.{name} many and required must be booleans")
        fields[name] = Field(selector, attr=attr, regex=regex, many=many, required=required)
    return MappingProxyType(fields)


def _policy(data: Mapping[str, object], base_dir: Path) -> tuple[PilotPolicy, tuple[Path, ...]]:
    _closed(
        data,
        {
            "allowed_hosts", "trusted_browser_hosts", "allowed_local_roots", "enabled_adapters",
            "credentials", "report_private_content",
        },
        "policy",
    )
    allowed_hosts = tuple(_canonical_host(item, "policy.allowed_hosts") for item in _items(data, "allowed_hosts", "policy") if isinstance(item, str))
    if len(allowed_hosts) != len(_items(data, "allowed_hosts", "policy")) or len(set(allowed_hosts)) != len(allowed_hosts):
        raise ValueError("policy.allowed_hosts must contain unique host strings")
    trusted_hosts = tuple(_canonical_host(item, "policy.trusted_browser_hosts") for item in _items(data, "trusted_browser_hosts", "policy") if isinstance(item, str))
    if len(trusted_hosts) != len(_items(data, "trusted_browser_hosts", "policy")) or not set(trusted_hosts).issubset(allowed_hosts):
        raise ValueError("policy.trusted_browser_hosts must be unique allowed hosts")
    root_names: list[str] = []
    resolved_roots: list[Path] = []
    for item in _items(data, "allowed_local_roots", "policy"):
        if not isinstance(item, str) or not item:
            raise ValueError("policy.allowed_local_roots must contain non-empty strings")
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("policy.allowed_local_roots must contain relative paths")
        try:
            resolved = (base_dir / path).resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError("policy.allowed_local_roots must name existing directories") from error
        if not resolved.is_dir():
            raise ValueError("policy.allowed_local_roots must name directories")
        root_names.append(path.as_posix())
        resolved_roots.append(resolved)
    if len(set(root_names)) != len(root_names):
        raise ValueError("policy.allowed_local_roots must be unique")
    adapters: list[str] = []
    for item in _items(data, "enabled_adapters", "policy"):
        if not isinstance(item, str) or item not in ADAPTERS:
            raise ValueError("policy.enabled_adapters contains an unsupported adapter")
        adapters.append(item)
    if not adapters or len(set(adapters)) != len(adapters):
        raise ValueError("policy.enabled_adapters must contain unique adapters")
    credentials: list[str] = []
    for item in _items(data, "credentials", "policy"):
        if not isinstance(item, str):
            raise ValueError("credential name must be an uppercase environment variable name")
        credentials.append(_credential(item))
    if len(set(credentials)) != len(credentials):
        raise ValueError("policy.credentials must contain unique names")
    return (
        PilotPolicy(
            tuple(sorted(allowed_hosts)), tuple(sorted(trusted_hosts)), tuple(sorted(root_names)),
            tuple(sorted(adapters)), tuple(sorted(credentials)), _bool(data, "report_private_content", "policy", False),
        ),
        tuple(resolved_roots),
    )


def _source(data: Mapping[str, object], mode: str, policy: PilotPolicy, base_dir: Path, roots: tuple[Path, ...]) -> PilotSource:
    _closed(
        data,
        {
            "id", "adapter", "target", "fixture", "refresh_fixture", "visibility", "monitor", "required",
            "extraction", "options",
        },
        "source",
    )
    source_id = _slug(_string(data, "id", "source"), "source.id")
    adapter = _string(data, "adapter", "source")
    if adapter not in policy.enabled_adapters:
        raise ValueError(f"source adapter is not enabled: {adapter}")
    target = _string(data, "target", "source")
    fixture = _optional_string(data, "fixture", "source")
    refresh_fixture = _optional_string(data, "refresh_fixture", "source")
    if mode == "live" and refresh_fixture is not None:
        raise ValueError("live source may not define a refresh_fixture")
    monitor = _bool(data, "monitor", "source")
    if monitor and adapter not in MONITOR_ADAPTERS:
        raise ValueError(f"{adapter} does not support monitoring")
    if refresh_fixture is not None and (not monitor or adapter not in MONITOR_ADAPTERS):
        raise ValueError("refresh_fixture requires monitor on a monitoring adapter")
    visibility = _string(data, "visibility", "source")
    if visibility not in {"private", "public"}:
        raise ValueError("source.visibility must be private or public")
    required = _bool(data, "required", "source", True)
    resolved_target: Path | None = None
    resolved_fixture: Path | None = None
    resolved_refresh_fixture: Path | None = None
    if adapter in NETWORK_ADAPTERS:
        host = _network_host(target)
        if host not in policy.allowed_hosts:
            raise ValueError(f"network target host is not an allowed host: {host}")
        if adapter in PROVIDER_HOSTS and host not in PROVIDER_HOSTS[adapter]:
            raise ValueError(f"{adapter} target host is not a known provider host")
        if adapter == "browser" and host not in policy.trusted_browser_hosts:
            raise ValueError(f"browser target host is not a trusted browser host: {host}")
        if mode == "offline" and fixture is None:
            raise ValueError("offline network source requires a fixture")
        if mode == "live" and fixture is not None:
            raise ValueError("live source may not define a fixture")
    else:
        target, resolved_target = _relative_path(target, "source.target", base_dir, roots)
        if mode == "live" and fixture is not None:
            raise ValueError("live source may not define a fixture")
    if fixture is not None:
        fixture, resolved_fixture = _relative_path(fixture, "source.fixture", base_dir, roots)
    if refresh_fixture is not None:
        refresh_fixture, resolved_refresh_fixture = _relative_path(refresh_fixture, "source.refresh_fixture", base_dir, roots)
    return PilotSource(
        source_id, adapter, target, fixture, refresh_fixture, visibility, monitor, required,
        _extraction(data.get("extraction"), adapter), _options(data.get("options"), adapter),
        resolved_target, resolved_fixture, resolved_refresh_fixture,
    )


def validate_pilot_manifest(data: Mapping[str, object], base_dir: Path) -> PilotManifest:
    """Validate an untrusted manifest without fetching targets or reading secrets."""
    data = _mapping(data, "manifest")
    _closed(data, {"schema", "pilot_id", "title", "mode", "deployment", "policy", "missions"}, "manifest")
    schema = _string(data, "schema", "manifest")
    if schema != PILOT_MANIFEST_SCHEMA:
        raise ValueError(f"manifest.schema must be {PILOT_MANIFEST_SCHEMA}")
    pilot_id = _slug(_string(data, "pilot_id", "manifest"), "manifest.pilot_id")
    title = _string(data, "title", "manifest")
    mode = _string(data, "mode", "manifest")
    if mode not in {"offline", "live"}:
        raise ValueError("manifest.mode must be offline or live")
    deployment_data = _mapping(data.get("deployment"), "deployment")
    _closed(deployment_data, {"mode", "custodian"}, "deployment")
    deployment = PilotDeployment(_string(deployment_data, "mode", "deployment"), _string(deployment_data, "custodian", "deployment"))
    if deployment.mode not in {"workstation", "customer_hosted", "zentropy_managed"}:
        raise ValueError("deployment.mode must be workstation, customer_hosted, or zentropy_managed")
    if deployment.custodian not in {"customer", "zentropy", "shared"}:
        raise ValueError("deployment.custodian must be customer, zentropy, or shared")
    resolved_base = Path(base_dir).resolve(strict=True)
    policy, roots = _policy(_mapping(data.get("policy"), "policy"), resolved_base)
    missions: list[PilotMission] = []
    mission_ids: set[str] = set()
    source_ids: set[str] = set()
    for raw_mission in _items(data, "missions", "manifest"):
        mission_data = _mapping(raw_mission, "mission")
        _closed(mission_data, {"id", "title", "sources"}, "mission")
        mission_id = _slug(_string(mission_data, "id", "mission"), "mission.id")
        if mission_id in mission_ids:
            raise ValueError(f"duplicate mission id: {mission_id}")
        mission_ids.add(mission_id)
        sources: list[PilotSource] = []
        for raw_source in _items(mission_data, "sources", "mission"):
            item = _source(_mapping(raw_source, "source"), mode, policy, resolved_base, roots)
            if item.id in source_ids:
                raise ValueError(f"duplicate source id: {item.id}")
            source_ids.add(item.id)
            sources.append(item)
        if not sources:
            raise ValueError("mission.sources must not be empty")
        missions.append(PilotMission(mission_id, _string(mission_data, "title", "mission"), tuple(sources)))
    if not missions:
        raise ValueError("manifest.missions must not be empty")
    return PilotManifest(schema, pilot_id, title, mode, deployment, policy, tuple(missions), resolved_base)


def _field_payload(field: Field) -> dict[str, object]:
    return {
        "selector": field.selector,
        "attr": field.attr,
        "regex": field.regex,
        "many": field.many,
        "required": field.required,
    }


def manifest_payload(manifest: PilotManifest) -> dict[str, object]:
    """Return the portable manifest representation used to compute its digest."""
    return {
        "schema": manifest.schema,
        "pilot_id": manifest.pilot_id,
        "title": manifest.title,
        "mode": manifest.mode,
        "deployment": {"mode": manifest.deployment.mode, "custodian": manifest.deployment.custodian},
        "policy": {
            "allowed_hosts": list(manifest.policy.allowed_hosts),
            "trusted_browser_hosts": list(manifest.policy.trusted_browser_hosts),
            "allowed_local_roots": list(manifest.policy.allowed_local_roots),
            "enabled_adapters": list(manifest.policy.enabled_adapters),
            "credentials": list(manifest.policy.credentials),
            "report_private_content": manifest.policy.report_private_content,
        },
        "missions": [
            {
                "id": mission.id,
                "title": mission.title,
                "sources": [
                    {
                        "id": source.id,
                        "adapter": source.adapter,
                        "target": source.target,
                        "fixture": source.fixture,
                        "refresh_fixture": source.refresh_fixture,
                        "visibility": source.visibility,
                        "monitor": source.monitor,
                        "required": source.required,
                        "extraction": (
                            {name: _field_payload(field) for name, field in source.extraction.items()}
                            if source.extraction is not None else None
                        ),
                        "options": _thaw_json(source.options),
                    }
                    for source in mission.sources
                ],
            }
            for mission in manifest.missions
        ],
    }


def manifest_digest(manifest: PilotManifest) -> str:
    raw = json.dumps(manifest_payload(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_pilot_manifest(path: str | Path) -> PilotManifest:
    """Load a JSON manifest using the manifest file's parent as its local root."""
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid pilot manifest JSON") from error
    return validate_pilot_manifest(_mapping(data, "manifest"), manifest_path.parent)
