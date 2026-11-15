"""Custody vocabulary of the pilot manifest, by format version.

Format 2 names who holds a deployment with role words: a deployment is run on a
workstation, hosted by the customer, or managed by the provider, and the
custodian is the customer, the provider, or shared. Format 1 used two other
spellings for the provider. Gather still reads them, maps them to the format 2
words, and never writes them.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PILOT_MANIFEST_SCHEMA = "gather.pilot-manifest/2"
PILOT_MANIFEST_SCHEMA_V1 = "gather.pilot-manifest/1"
READABLE_MANIFEST_SCHEMAS = (PILOT_MANIFEST_SCHEMA, PILOT_MANIFEST_SCHEMA_V1)

DEPLOYMENT_MODES = ("workstation", "customer_hosted", "provider_managed")
CUSTODIANS = ("customer", "provider", "shared")

# Format 1 only. Read, mapped, never written.
V1_MODE_RENAMES = {"zentropy_managed": "provider_managed"}
V1_CUSTODIAN_RENAMES = {"zentropy": "provider"}
_V1_MODES = frozenset(DEPLOYMENT_MODES) - frozenset(V1_MODE_RENAMES.values()) | frozenset(V1_MODE_RENAMES)
_V1_CUSTODIANS = frozenset(CUSTODIANS) - frozenset(V1_CUSTODIAN_RENAMES.values()) | frozenset(V1_CUSTODIAN_RENAMES)

MIGRATE_HINT = "run `gather pilot migrate-manifest <manifest.json> --write`"


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(values[:-1]) + ", or " + values[-1]


def recorded_deployment_valid(schema: object, mode: object, custodian: object) -> bool:
    """Whether a stored manifest's custody values belong to its own format."""
    if schema == PILOT_MANIFEST_SCHEMA:
        return mode in DEPLOYMENT_MODES and custodian in CUSTODIANS
    if schema == PILOT_MANIFEST_SCHEMA_V1:
        return mode in _V1_MODES and custodian in _V1_CUSTODIANS
    return False


def uses_retired_value(mode: object, custodian: object) -> bool:
    return mode in V1_MODE_RENAMES or custodian in V1_CUSTODIAN_RENAMES


def read_deployment(schema: str, mode: str, custodian: str) -> tuple[str, str, tuple[str, ...]]:
    """Return the format 2 mode and custodian, and what the input used that is deprecated.

    Raises ValueError for a value outside the vocabulary of the manifest's own
    format, so a format 2 manifest cannot carry a format 1 spelling.
    """
    if schema == PILOT_MANIFEST_SCHEMA:
        if mode not in DEPLOYMENT_MODES:
            raise ValueError(f"deployment.mode must be {_listed(DEPLOYMENT_MODES)}")
        if custodian not in CUSTODIANS:
            raise ValueError(f"deployment.custodian must be {_listed(CUSTODIANS)}")
        return mode, custodian, ()
    if schema != PILOT_MANIFEST_SCHEMA_V1:
        raise ValueError(f"manifest.schema must be {PILOT_MANIFEST_SCHEMA}")
    if mode not in _V1_MODES:
        raise ValueError(
            f"deployment.mode must be {_listed(DEPLOYMENT_MODES)} "
            f"(this is a format 1 manifest: {MIGRATE_HINT})"
        )
    if custodian not in _V1_CUSTODIANS:
        raise ValueError(
            f"deployment.custodian must be {_listed(CUSTODIANS)} "
            f"(this is a format 1 manifest: {MIGRATE_HINT})"
        )
    deprecations = [f"manifest.schema {PILOT_MANIFEST_SCHEMA_V1} is read as {PILOT_MANIFEST_SCHEMA}"]
    if mode in V1_MODE_RENAMES:
        deprecations.append(f"deployment.mode {mode} is read as {V1_MODE_RENAMES[mode]}")
    if custodian in V1_CUSTODIAN_RENAMES:
        deprecations.append(f"deployment.custodian {custodian} is read as {V1_CUSTODIAN_RENAMES[custodian]}")
    return (
        V1_MODE_RENAMES.get(mode, mode),
        V1_CUSTODIAN_RENAMES.get(custodian, custodian),
        tuple(deprecations),
    )


@dataclass(frozen=True, slots=True)
class ManifestMigration:
    """What migrating one authored manifest file changes."""

    path: Path
    changes: tuple[tuple[str, str, str], ...]
    written: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path.name,
            "changes": [{"field": field, "from": old, "to": new} for field, old, new in self.changes],
            "written": self.written,
        }


def migrate_manifest_data(data: Mapping[str, object]) -> tuple[dict[str, object], tuple[tuple[str, str, str], ...]]:
    """Return a format 2 copy of a manifest mapping and the list of changed fields.

    Key order is kept. Raises ValueError when the schema or a custody value is
    outside what its format allows; nothing is guessed.
    """
    schema = data.get("schema")
    deployment = data.get("deployment")
    if not isinstance(schema, str) or schema not in READABLE_MANIFEST_SCHEMAS:
        raise ValueError(f"manifest.schema must be {PILOT_MANIFEST_SCHEMA} or {PILOT_MANIFEST_SCHEMA_V1}")
    if not isinstance(deployment, Mapping):
        raise ValueError("deployment must be an object")
    mode, custodian = deployment.get("mode"), deployment.get("custodian")
    if not isinstance(mode, str) or not isinstance(custodian, str):
        raise ValueError("deployment.mode and deployment.custodian must be strings")
    new_mode, new_custodian, _ = read_deployment(schema, mode, custodian)
    changes: list[tuple[str, str, str]] = []
    if schema != PILOT_MANIFEST_SCHEMA:
        changes.append(("schema", schema, PILOT_MANIFEST_SCHEMA))
    if new_mode != mode:
        changes.append(("deployment.mode", mode, new_mode))
    if new_custodian != custodian:
        changes.append(("deployment.custodian", custodian, new_custodian))
    migrated: dict[str, object] = {}
    for key, value in data.items():
        if key == "schema":
            migrated[key] = PILOT_MANIFEST_SCHEMA
        elif key == "deployment":
            migrated[key] = {
                name: new_mode if name == "mode" else new_custodian if name == "custodian" else item
                for name, item in deployment.items()
            }
        else:
            migrated[key] = value
    return migrated, tuple(changes)


def migrate_manifest_file(path: str | Path, *, write: bool = False) -> ManifestMigration:
    """Plan, and with ``write`` apply, the format 2 migration of an authored manifest.

    The dry run reads only. A write validates the migrated manifest first and
    then replaces the file in one step, so a refused manifest is left as it was.
    """
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid pilot manifest JSON") from error
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    migrated, changes = migrate_manifest_data(data)
    if not write or not changes:
        return ManifestMigration(manifest_path, changes, False)
    from gather.pilot_manifest import validate_pilot_manifest

    validate_pilot_manifest(migrated, manifest_path.parent)
    body = (json.dumps(migrated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    handle, temp_name = tempfile.mkstemp(dir=manifest_path.parent, prefix=manifest_path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
        os.replace(temp_name, manifest_path)
    except OSError:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return ManifestMigration(manifest_path, changes, True)
