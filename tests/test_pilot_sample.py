"""Checked-in redacted sample drift and privacy tests."""
from __future__ import annotations

import json
import re
import socket
import zipfile
from pathlib import Path

import pytest

from gather.pilot import run_pilot
from gather.pilot_bundle import create_pilot_bundle
from gather.pilot_manifest import load_pilot_manifest

REPO = Path(__file__).resolve().parent.parent
SAMPLE = REPO / "examples" / "pilot" / "sample"
SHOWCASE = REPO / "examples" / "pilot" / "showcase-offline.json"
CLOCK = 1700000000.0

# Language that must never appear in a public, shared artifact.
FORBIDDEN_PATTERNS = [
    re.compile(r"[A-Za-z]:\\Users\\", re.I),       # absolute Windows user paths
    re.compile(r"/Users/", re.I),                  # absolute POSIX user paths
    re.compile(r"/home/", re.I),
    re.compile(r"AppData", re.I),
    re.compile(r"\.env\b", re.I),
    re.compile(r"secret|private[_-]?key|api[_-]?key|token", re.I),
    re.compile(r"https?://", re.I),                # remote HTML assets
    re.compile(r"Pioneer Square|PSL", re.I),
    re.compile(r"buyout|purchase price|for sale", re.I),
    re.compile(r"price|pricing|\$\s?\d|negotiat", re.I),
    re.compile(r"contact@|\.com\b", re.I),         # contact / external domains
]
# Private fixture bodies that must never leak into the shared sample.
PRIVATE_BODIES = [
    "track portfolio status changes",
    "keep the scholarly reference deduplicated",
    "operator's working note for the pilot",
]


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network opened")),
    )


@pytest.fixture()
def generated_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    monkeypatch.chdir(REPO)
    manifest = load_pilot_manifest(SHOWCASE)
    root = tmp_path / "pilot"
    run_pilot(manifest, root, clock=lambda: CLOCK)
    bundle = tmp_path / "shared.zip"
    create_pilot_bundle(root, bundle, visibility="shared")
    with zipfile.ZipFile(bundle) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _sample_bytes(name: str) -> bytes:
    return (SAMPLE / name).read_bytes()


def test_sample_report_json_matches_regenerated(generated_sample) -> None:
    assert json.loads(_sample_bytes("report.json")) == json.loads(
        generated_sample["report.json"]
    )


def test_sample_pilot_receipt_matches_regenerated(generated_sample) -> None:
    assert json.loads(_sample_bytes("pilot-receipt.json")) == json.loads(
        generated_sample["pilot-receipt.json"]
    )


def test_sample_manifest_digest_matches_regenerated(generated_sample) -> None:
    assert json.loads(_sample_bytes("manifest-digest.json")) == json.loads(
        generated_sample["manifest-digest.json"]
    )


def test_sample_bundle_receipt_matches_regenerated(generated_sample) -> None:
    assert json.loads(_sample_bytes("bundle-receipt.json")) == json.loads(
        generated_sample["bundle-receipt.json"]
    )


def test_sample_html_matches_regenerated(generated_sample) -> None:
    assert _sample_bytes("report.html") == generated_sample["report.html"]


@pytest.mark.parametrize("name", ["report.json", "report.html", "pilot-receipt.json",
                                  "manifest-digest.json", "bundle-receipt.json"])
def test_sample_has_no_absolute_paths(name: str) -> None:
    text = _sample_bytes(name).decode("utf-8", "replace")
    for pat in FORBIDDEN_PATTERNS[:5]:
        assert pat.search(text) is None, f"{name}: forbidden pattern {pat.pattern!r} present"


@pytest.mark.parametrize("name", ["report.json", "report.html", "pilot-receipt.json",
                                  "manifest-digest.json", "bundle-receipt.json"])
def test_sample_has_no_private_bodies(name: str) -> None:
    text = _sample_bytes(name).decode("utf-8", "replace").lower()
    for body in PRIVATE_BODIES:
        assert body not in text, f"{name}: private body {body!r} leaked"


@pytest.mark.parametrize("name", ["report.json", "report.html", "pilot-receipt.json",
                                  "manifest-digest.json", "bundle-receipt.json"])
def test_sample_has_no_commercial_language(name: str) -> None:
    text = _sample_bytes(name).decode("utf-8", "replace")
    for pat in FORBIDDEN_PATTERNS[7:]:
        assert pat.search(text) is None, f"{name}: forbidden pattern {pat.pattern!r} present"


def test_sample_html_has_no_remote_assets() -> None:
    """The HTML view must be self-contained: no script, font, image, or fetch URL."""
    text = _sample_bytes("report.html").decode("utf-8", "replace")
    assert "https://" not in text
    assert "http://" not in text
    for tag in ("<script", "<img", "<link", "url(", "@import"):
        assert tag not in text
