"""CLI command group and exit-semantics tests for the pilot engine."""
from __future__ import annotations

import json
import socket
import zipfile
from pathlib import Path

import pytest

from gather.cli import main
from gather.pilot_manifest import validate_pilot_manifest

HTML = "<!doctype html><html><body><h1>Portfolio</h1><p>Status: seed</p></body></html>"


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pilot CLI opened a network socket")

    monkeypatch.setattr(socket, "create_connection", forbidden)


def _showcase(tmp_path: Path) -> Path:
    """Write a manifest config + fixtures; return the manifest path."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "portfolio.html").write_text(HTML, encoding="utf-8")
    manifest = {
        "schema": "gather.pilot-manifest/1",
        "pilot_id": "cli-showcase",
        "title": "CLI showcase",
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
    }
    path = tmp_path / "showcase.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    # validate once to prove the fixture shape is accepted
    validate_pilot_manifest(manifest, tmp_path)
    return path


def test_pilot_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["pilot", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out
    assert "refresh" in out
    assert "verify" in out
    assert "bundle" in out


def test_pilot_run_writes_root_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    code = main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    assert code == 0
    assert (out / "report.json").exists()
    assert (out / "pilot-receipt.json").exists()
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["action"] == "run"
    assert emitted["manifest_digest"]


def test_pilot_run_refuses_invalid_manifest_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "wrong"}', encoding="utf-8")
    out = tmp_path / "pilot"
    code = main(["pilot", "run", str(bad), "--output", str(out)])
    assert code == 2
    err = capsys.readouterr().err
    assert "manifest" in err.lower()


def test_pilot_verify_exits_zero_on_clean_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    assert main(["pilot", "verify", str(out), "--json"]) == 0


def test_pilot_verify_exits_one_on_tampered_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    # Tamper one content-addressed corpus object body.
    obj = next(p for p in (out / "corpus" / "objects").rglob("*") if p.is_file())
    obj.write_bytes(obj.read_bytes() + b"tampered")
    assert main(["pilot", "verify", str(out)]) == 1


def test_pilot_bundle_shared_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    bundle = tmp_path / "shared.zip"
    code = main(["pilot", "bundle", str(out), "--output", str(bundle), "--visibility", "shared"])
    assert code == 0
    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
    assert "report.json" in names
    assert not any(n.startswith("corpus") for n in names)


def test_pilot_bundle_full_refuses_without_confirmation_exit_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    bundle = tmp_path / "full.zip"
    code = main(["pilot", "bundle", str(out), "--output", str(bundle), "--visibility", "full"])
    assert code != 0
    assert not bundle.exists()


def test_pilot_no_traceback_or_private_diagnostic_in_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_network(monkeypatch)
    manifest = _showcase(tmp_path)
    out = tmp_path / "pilot"
    main(["pilot", "run", str(manifest), "--output", str(out), "--json"])
    bundle = tmp_path / "full.zip"
    main(["pilot", "bundle", str(out), "--output", str(bundle), "--visibility", "full"])
    err = capsys.readouterr().err
    assert "Traceback" not in err
