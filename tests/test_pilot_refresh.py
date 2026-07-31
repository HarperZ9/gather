"""Monitoring refresh and receipt-history tests for the pilot engine."""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from gather.pilot import PilotRefusal, refresh_pilot, run_pilot, verify_pilot
from gather.pilot_manifest import validate_pilot_manifest

HTML_V1 = (
    "<!doctype html><html><head><title>Venture portfolio</title></head>"
    "<body><h1>Acme</h1><p>Status: seed</p></body></html>"
)
HTML_V2 = (
    "<!doctype html><html><head><title>Venture portfolio</title></head>"
    "<body><h1>Acme</h1><p>Status: series-a</p></body></html>"
)


def showcase_manifest(tmp_path: Path) -> object:
    """One offline mission with a single monitored web source.

    The source carries an initial fixture (v1) and a refresh fixture (v2) so a
    first refresh observes CHANGED and a second refresh observes UNCHANGED.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "portfolio-v1.html").write_text(HTML_V1, encoding="utf-8")
    (fixtures / "portfolio-v2.html").write_text(HTML_V2, encoding="utf-8")
    return validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "showcase-refresh",
            "title": "Refresh showcase",
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
                    "id": "venture-watch",
                    "title": "Venture watch",
                    "sources": [
                        {
                            "id": "portfolio",
                            "adapter": "web",
                            "target": "https://example.org/portfolio",
                            "fixture": "fixtures/portfolio-v1.html",
                            "refresh_fixture": "fixtures/portfolio-v2.html",
                            "visibility": "public",
                            "monitor": True,
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


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("refresh opened a network socket")

    monkeypatch.setattr(socket, "create_connection", forbidden)


def _make_portable(manifest_home: Path, root: Path) -> None:
    """Bundle the manifest's fixtures into the evidence root so refresh, which
    reconstructs the manifest from root/manifest.json, can reach them. A
    retained offline pilot is self-contained: its fixtures travel with it."""
    config = manifest_home / "fixtures"
    if config.exists():
        shutil.copytree(config, root / "fixtures", dirs_exist_ok=True)


def test_initial_run_reports_new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"
    result = run_pilot(manifest, root, clock=lambda: 100.0)

    assert result.monitor_report is not None
    assert result.monitor_report["counts"]["NEW"] == 1
    assert verify_pilot(root).ok


def test_refresh_changes_then_stabilizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"

    run_pilot(manifest, root, clock=lambda: 100.0)
    _make_portable(tmp_path, root)
    first = refresh_pilot(root, clock=lambda: 200.0)
    second = refresh_pilot(root, clock=lambda: 300.0)

    assert first.monitor_report["counts"]["CHANGED"] == 1
    assert second.monitor_report["counts"]["UNCHANGED"] == 1
    assert sorted(path.name for path in (root / "history").iterdir()) == [
        "0001-pilot-receipt.json",
        "0001-report.html",
        "0001-report.json",
        "0002-pilot-receipt.json",
        "0002-report.html",
        "0002-report.json",
    ]
    assert verify_pilot(root).ok


def test_refresh_emits_monitor_completed_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 100.0)
    _make_portable(tmp_path, root)

    events: list[object] = []

    class Sink:
        def emit(self, event: object) -> None:
            events.append(event)

    refresh_pilot(root, clock=lambda: 200.0, event_sink=Sink())
    kinds = [event.kind for event in events]  # type: ignore[attr-defined]
    assert "monitor_completed" in kinds
    assert kinds[-1] == "run_completed"


def test_refresh_refuses_tampered_current_receipt_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 100.0)

    receipt_path = root / "pilot-receipt.json"
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["gather_version"] = "0.0.0-tampered"
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")

    called = {"capture": False}
    monkeypatch.setattr(
        "gather.pilot.capture_source",
        lambda *_a, **_k: called.__setitem__("capture", True),
    )

    snapshot = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    with pytest.raises(PilotRefusal):
        refresh_pilot(root, clock=lambda: 200.0)
    assert called["capture"] is False
    for name, before in snapshot.items():
        assert (root / name).read_bytes() == before, f"current artifact {name} mutated on refusal"


def test_refresh_appends_items_and_grows_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gather.store import Corpus

    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 100.0)
    _make_portable(tmp_path, root)
    before = Corpus(str(root / "corpus")).stats()["items"]
    refresh_pilot(root, clock=lambda: 200.0)
    after = Corpus(str(root / "corpus")).stats()["items"]
    assert after == before + 1


def test_refresh_uses_only_manifest_json_inside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    manifest = showcase_manifest(tmp_path)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 100.0)
    _make_portable(tmp_path, root)
    # refresh_pilot accepts no manifest override; it reconstructs from manifest.json.
    result = refresh_pilot(root, clock=lambda: 200.0)
    assert result.monitor_report is not None
    assert verify_pilot(root).ok
