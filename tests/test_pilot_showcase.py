"""End-to-end representative showcase tests."""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from gather.pilot import refresh_pilot, run_pilot, verify_pilot
from gather.pilot_manifest import load_pilot_manifest

SHOWCASE = Path("examples/pilot/showcase-offline.json")


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network opened")),
    )


def _make_portable(root: Path) -> None:
    """Bundle the showcase fixtures into the evidence root so refresh resolves them."""
    fixtures = Path("examples/pilot/fixtures")
    if fixtures.exists():
        shutil.copytree(fixtures, root / "fixtures", dirs_exist_ok=True)


def test_offline_showcase_is_deterministic_and_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    one = tmp_path / "one"
    two = tmp_path / "two"

    run_pilot(manifest, one, clock=lambda: 1700000000.0)
    run_pilot(manifest, two, clock=lambda: 1700000000.0)

    assert json.loads((one / "report.json").read_text()) == json.loads(
        (two / "report.json").read_text()
    )
    assert verify_pilot(one).ok
    assert verify_pilot(two).ok


def test_offline_showcase_has_three_missions_and_six_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_text())

    mission_ids = [m["id"] for m in report["missions"]]
    assert mission_ids == [
        "venture-market-diligence",
        "technical-scientific-research",
        "media-operational-intelligence",
    ]
    adapters = {s["adapter"] for m in report["missions"] for s in m["sources"]}
    assert len(adapters) >= 6
    assert {"web", "feed", "scholar", "video", "api", "docs"} <= adapters


def test_offline_showcase_has_one_private_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_text())
    private = [
        s for m in report["missions"] for s in m["sources"] if s["visibility"] == "private"
    ]
    assert len(private) == 1
    # private sources never expose their target
    assert "target" not in private[0]


def test_offline_showcase_has_grounded_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    report = json.loads((root / "report.json").read_text())
    extractions = report["extractions"]
    assert len(extractions) == 1
    org = next(f for f in extractions[0]["fields"] if f["name"] == "organization")
    assert org["status"] == "extracted"
    assert "Lumencast Ventures" in org["value"]


def test_offline_showcase_dedups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    from gather.store import Corpus

    by_source = Corpus(str(root / "corpus")).stats()["by_source"]
    # Scholar federates the same DOI across two providers; federation dedups to one paper.
    assert by_source.get("scholar") == 1


def test_offline_showcase_refresh_new_then_changed_then_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    initial = run_pilot(manifest, root, clock=lambda: 100.0)
    assert initial.monitor_report["counts"]["NEW"] == 1

    _make_portable(root)
    first = refresh_pilot(root, clock=lambda: 200.0)
    assert first.monitor_report["counts"]["CHANGED"] == 1

    second = refresh_pilot(root, clock=lambda: 300.0)
    assert second.monitor_report["counts"]["UNCHANGED"] == 1
    assert verify_pilot(root).ok
