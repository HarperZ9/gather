"""Deterministic shared and full pilot bundle tests."""
from __future__ import annotations

import io
import json
import socket
import zipfile
from pathlib import Path

import pytest

from gather.pilot import PilotRefusal, run_pilot
from gather.pilot_bundle import (
    PILOT_BUNDLE_SCHEMA,
    PilotBundleReceipt,
    create_pilot_bundle,
    verify_pilot_bundle,
)
from gather.pilot_manifest import validate_pilot_manifest

HTML = "<!doctype html><html><body><h1>Portfolio</h1><p>Status: seed</p></body></html>"


def _root(tmp_path: Path) -> tuple[Path, object]:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "portfolio.html").write_text(HTML, encoding="utf-8")
    manifest = validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "bundle-showcase",
            "title": "Bundle showcase",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": ["example.org"],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["web"],
                "credentials": [],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "venture",
                    "title": "Venture",
                    "sources": [
                        {
                            "id": "portfolio",
                            "adapter": "web",
                            "target": "https://example.org/portfolio",
                            "fixture": "fixtures/portfolio.html",
                            "refresh_fixture": None,
                            "visibility": "public",
                            "monitor": False,
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
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 100.0)
    return root, manifest


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("bundle opened a network socket")

    monkeypatch.setattr(socket, "create_connection", forbidden)


def _member_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(zf.namelist())


def _member_timestamps(zip_path: Path) -> set[tuple[int, int, int, int, int, int]]:
    with zipfile.ZipFile(zip_path) as zf:
        return {info.date_time for info in zf.infolist()}


def test_shared_bundle_has_exactly_the_safe_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    assert _member_names(out) == [
        "bundle-receipt.json",
        "manifest-digest.json",
        "pilot-receipt.json",
        "report.html",
        "report.json",
    ]


def test_shared_bundle_omits_private_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    names = _member_names(out)
    assert "corpus/" not in names
    assert not any(n.startswith("corpus") for n in names)
    assert "monitor-state.json" not in names
    assert not any(n.startswith("history") for n in names)


def test_shared_bundle_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    one = tmp_path / "one.zip"
    two = tmp_path / "two.zip"
    create_pilot_bundle(root, one, visibility="shared")
    create_pilot_bundle(root, two, visibility="shared")
    assert one.read_bytes() == two.read_bytes()


def test_shared_bundle_member_timestamps_are_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    assert _member_timestamps(out) == {(1980, 1, 1, 0, 0, 0)}


def test_shared_bundle_member_paths_are_relative_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    for name in _member_names(out):
        assert "\\" not in name
        assert not Path(name).is_absolute()
        assert ".." not in Path(name).parts


def test_shared_bundle_refuses_private_content_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    # Tamper the manifest snapshot to request private content; shared must refuse.
    manifest_path = root / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["policy"]["report_private_content"] = True
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "shared.zip"
    with pytest.raises(PilotRefusal):
        create_pilot_bundle(root, out, visibility="shared")


def test_full_bundle_refuses_without_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "full.zip"
    with pytest.raises(PilotRefusal):
        create_pilot_bundle(root, out, visibility="full")


def test_full_bundle_contains_corpus_when_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "full.zip"
    create_pilot_bundle(root, out, visibility="full", include_private_evidence=True)
    names = _member_names(out)
    assert any(n.startswith("corpus/") for n in names)
    assert "bundle-receipt.json" in names


def test_shared_bundle_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    assert verify_pilot_bundle(out).ok


def test_tampered_member_breaks_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    create_pilot_bundle(root, out, visibility="shared")
    # Rewrite one member byte in place, preserving the deterministic ordering.
    data = io.BytesIO(out.read_bytes())
    with zipfile.ZipFile(data, "r") as zf:
        members = {info.filename: zf.read(info.filename) for info in zf.infolist()}
    members["report.json"] = members["report.json"][:-1] + (b"}" if members["report.json"][-1:] != b"}" else b"]")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_STORED) as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zf.writestr(info, members[name])
    out.write_bytes(data.getvalue())
    assert not verify_pilot_bundle(out).ok


def test_bundle_receipt_carries_closed_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    root, _manifest = _root(tmp_path)
    out = tmp_path / "shared.zip"
    receipt = create_pilot_bundle(root, out, visibility="shared")
    assert receipt.schema == PILOT_BUNDLE_SCHEMA
    assert receipt.visibility == "shared"
    assert isinstance(receipt, PilotBundleReceipt)
    assert receipt.bundle_digest
