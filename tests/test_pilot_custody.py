"""Format 2 custody names: old values read, new values written, migration, refusals."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gather.cli import main
from gather.pilot import PilotRefusal, refresh_pilot, run_pilot, verify_pilot
from gather.pilot_custody import (
    PILOT_MANIFEST_SCHEMA,
    PILOT_MANIFEST_SCHEMA_V1,
    V1_CUSTODIAN_RENAMES,
    V1_MODE_RENAMES,
    migrate_manifest_file,
)
from gather.pilot_manifest import load_pilot_manifest, manifest_digest, manifest_payload
from gather.pilot_report import _valid_normalized_manifest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OLD_MODE = next(iter(V1_MODE_RENAMES))
OLD_CUSTODIAN = next(iter(V1_CUSTODIAN_RENAMES))
RETIRED = (OLD_MODE, OLD_CUSTODIAN)
NEW = {"mode": "provider_managed", "custodian": "provider"}


def write_manifest(home: Path, schema: str, mode: str, custodian: str) -> Path:
    (home / "fixtures").mkdir(exist_ok=True)
    (home / "fixtures" / "note.html").write_text("<h1>Note</h1><p>Body.</p>", encoding="utf-8")
    data = {
        "schema": schema, "pilot_id": "custody", "title": "Custody names", "mode": "offline",
        "deployment": {"mode": mode, "custodian": custodian},
        "policy": {
            "allowed_hosts": [], "trusted_browser_hosts": [], "allowed_local_roots": ["fixtures"],
            "enabled_adapters": ["docs"], "credentials": [], "report_private_content": False,
        },
        "missions": [{"id": "mission-one", "title": "Offline evidence", "sources": [{
            "id": "source-one", "adapter": "docs", "target": "fixtures/note.html", "fixture": None,
            "refresh_fixture": None, "visibility": "public", "monitor": False, "required": True,
            "extraction": None, "options": {},
        }]}],
    }
    path = home / "manifest.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def files_of(root: Path) -> dict[str, bytes]:
    return {item.relative_to(root).as_posix(): item.read_bytes() for item in root.rglob("*") if item.is_file()}


def test_format_one_values_are_read_as_format_two_with_deprecations(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA_V1, OLD_MODE, OLD_CUSTODIAN)
    with pytest.warns(DeprecationWarning) as caught:
        manifest = load_pilot_manifest(path)

    assert manifest.schema == PILOT_MANIFEST_SCHEMA
    assert (manifest.deployment.mode, manifest.deployment.custodian) == ("provider_managed", "provider")
    assert manifest.deprecations == (
        f"manifest.schema {PILOT_MANIFEST_SCHEMA_V1} is read as {PILOT_MANIFEST_SCHEMA}",
        f"deployment.mode {OLD_MODE} is read as provider_managed",
        f"deployment.custodian {OLD_CUSTODIAN} is read as provider",
    )
    assert len(caught) == 3
    assert all("migrate-manifest" in str(item.message) for item in caught)


def test_format_two_manifest_loads_with_no_deprecation(tmp_path: Path, recwarn: pytest.WarningsRecorder) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA, "provider_managed", "provider")
    manifest = load_pilot_manifest(path)

    assert manifest.deprecations == ()
    assert [item for item in recwarn if item.category is DeprecationWarning] == []


def test_a_run_from_a_format_one_manifest_writes_no_old_value(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA_V1, OLD_MODE, OLD_CUSTODIAN)
    with pytest.warns(DeprecationWarning):
        manifest = load_pilot_manifest(path)
    payload = manifest_payload(manifest)
    assert payload["schema"] == PILOT_MANIFEST_SCHEMA
    assert payload["deployment"] == NEW

    root = tmp_path / "root"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    assert verify_pilot(root).ok
    written = files_of(root)
    assert len(written) >= 5
    for name, body in written.items():
        for old in RETIRED:
            assert old.encode() not in body, f"{name} holds a format 1 value"
        assert PILOT_MANIFEST_SCHEMA_V1.encode() not in body, f"{name} names format 1"
    assert json.loads(written["manifest.json"])["deployment"] == NEW
    assert json.loads(written["report.json"])["deployment"] == NEW


def test_migration_round_trip_dry_run_then_write(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA_V1, OLD_MODE, OLD_CUSTODIAN)
    before = path.read_bytes()
    with pytest.warns(DeprecationWarning):
        digest_through_compatibility = manifest_digest(load_pilot_manifest(path))

    plan = migrate_manifest_file(path)
    assert plan.written is False
    assert plan.changes == (
        ("schema", PILOT_MANIFEST_SCHEMA_V1, PILOT_MANIFEST_SCHEMA),
        ("deployment.mode", OLD_MODE, "provider_managed"),
        ("deployment.custodian", OLD_CUSTODIAN, "provider"),
    )
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["fixtures", "manifest.json"]

    applied = migrate_manifest_file(path, write=True)
    assert applied.written is True and applied.changes == plan.changes
    after = path.read_text(encoding="utf-8")
    assert all(old not in after for old in RETIRED)
    assert list(json.loads(after)) == list(json.loads(before))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["fixtures", "manifest.json"]

    migrated = load_pilot_manifest(path)
    assert migrated.deprecations == ()
    assert manifest_digest(migrated) == digest_through_compatibility

    again = migrate_manifest_file(path, write=True)
    assert again.changes == () and again.written is False


@pytest.mark.parametrize(
    ("schema", "mode", "custodian", "message"),
    [
        (PILOT_MANIFEST_SCHEMA, OLD_MODE, "customer", "deployment.mode"),
        (PILOT_MANIFEST_SCHEMA, "workstation", OLD_CUSTODIAN, "deployment.custodian"),
        (PILOT_MANIFEST_SCHEMA_V1, "provider_managed", "customer", "deployment.mode"),
        (PILOT_MANIFEST_SCHEMA_V1, "workstation", "provider", "deployment.custodian"),
        (PILOT_MANIFEST_SCHEMA, "vendor_managed", "customer", "deployment.mode"),
        (PILOT_MANIFEST_SCHEMA_V1, "workstation", "nobody", "deployment.custodian"),
        ("gather.pilot-manifest/3", "workstation", "customer", "manifest.schema"),
    ],
)
def test_a_planted_unknown_value_is_refused_and_left_unchanged(
    tmp_path: Path, schema: str, mode: str, custodian: str, message: str,
) -> None:
    path = write_manifest(tmp_path, schema, mode, custodian)
    before = path.read_bytes()

    with pytest.raises(ValueError, match=message):
        load_pilot_manifest(path)
    with pytest.raises(ValueError, match=message):
        migrate_manifest_file(path, write=True)
    assert main(["pilot", "migrate-manifest", str(path), "--write"]) == 2
    assert main(["pilot", "run", str(path), "--output", str(tmp_path / "root")]) == 2
    assert path.read_bytes() == before
    assert not (tmp_path / "root").exists()


def test_migrate_command_is_a_dry_run_until_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA_V1, OLD_MODE, "shared")
    before = path.read_bytes()

    assert main(["pilot", "migrate-manifest", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"deployment.mode: {OLD_MODE} -> provider_managed" in out
    assert "dry run: nothing written" in out
    assert path.read_bytes() == before

    assert main(["pilot", "migrate-manifest", str(path), "--write", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["written"] is True
    assert {change["field"] for change in result["changes"]} == {"schema", "deployment.mode"}
    assert json.loads(path.read_text(encoding="utf-8"))["deployment"] == {
        "mode": "provider_managed", "custodian": "shared",
    }

    assert main(["pilot", "migrate-manifest", str(path)]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_pilot_run_prints_each_deprecation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_manifest(tmp_path, PILOT_MANIFEST_SCHEMA_V1, "workstation", "customer")
    with pytest.warns(DeprecationWarning):
        code = main(["pilot", "run", str(path), "--output", str(tmp_path / "root")])
    assert code == 0
    err = capsys.readouterr().err
    assert f"deprecated: manifest.schema {PILOT_MANIFEST_SCHEMA_V1} is read as {PILOT_MANIFEST_SCHEMA}" in err
    assert "migrate-manifest" in err


def test_recorded_manifest_values_must_match_their_own_format() -> None:
    stored = json.loads((FIXTURES / "pilot-root-format1-retired" / "manifest.json").read_text(encoding="utf-8"))
    assert stored["schema"] == PILOT_MANIFEST_SCHEMA_V1
    assert stored["deployment"] == {"mode": OLD_MODE, "custodian": OLD_CUSTODIAN}
    assert _valid_normalized_manifest(stored)

    assert not _valid_normalized_manifest({**stored, "schema": PILOT_MANIFEST_SCHEMA})
    assert not _valid_normalized_manifest({**stored, "deployment": {"mode": OLD_MODE, "custodian": "nobody"}})
    assert not _valid_normalized_manifest({**stored, "deployment": NEW})
    assert _valid_normalized_manifest({**stored, "schema": PILOT_MANIFEST_SCHEMA, "deployment": NEW})


def test_a_root_sealed_by_2_6_0_with_old_values_verifies_and_is_not_extended(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "pilot-root-format1-retired", root)
    before = files_of(root)

    assert verify_pilot(root).ok
    with pytest.raises(PilotRefusal, match="sealed in manifest format 1 with a retired custody value"):
        refresh_pilot(root)
    assert main(["pilot", "refresh", str(root)]) == 1
    assert files_of(root) == before
    assert verify_pilot(root).ok


def test_a_root_sealed_by_2_6_0_with_unchanged_values_refreshes_in_its_own_format(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "pilot-root-format1-plain", root)
    manifest_before = (root / "manifest.json").read_bytes()
    assert verify_pilot(root).ok

    refresh_pilot(root)

    assert (root / "manifest.json").read_bytes() == manifest_before
    assert verify_pilot(root).ok
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["deployment"] == {"mode": "customer_hosted", "custodian": "customer"}
