"""Standalone verifier contract: the vendored verify_pilot.py re-derives the seal.

The verifier at the repo root imports only the standard library. A stranger runs
it against a pilot output directory and it re-reads the sealed bytes, recomputes
each sha256 over the referenced artifact, and re-derives the history chain. This
test builds a real pilot output with the package, asserts a clean MATCH, then
flips one byte of report.json and asserts DRIFT.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gather.pilot import run_pilot, verify_pilot
from gather.pilot_manifest import validate_pilot_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFIER = REPO_ROOT / "verify_pilot.py"


def _build_pilot_root(tmp_path: Path) -> Path:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "secret-plan.txt").write_text("private body", encoding="utf-8")
    manifest = validate_pilot_manifest(
        {
            "schema": "gather.pilot-manifest/1",
            "pilot_id": "pilot-one",
            "title": "Evidence pilot",
            "mode": "offline",
            "deployment": {"mode": "workstation", "custodian": "customer"},
            "policy": {
                "allowed_hosts": [],
                "trusted_browser_hosts": [],
                "allowed_local_roots": ["fixtures"],
                "enabled_adapters": ["docs"],
                "credentials": [],
                "report_private_content": False,
            },
            "missions": [
                {
                    "id": "mission-one",
                    "title": "Private mission",
                    "sources": [
                        {
                            "id": "source-one",
                            "adapter": "docs",
                            "target": "fixtures/secret-plan.txt",
                            "fixture": None,
                            "refresh_fixture": None,
                            "visibility": "private",
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
    root = tmp_path / "out"
    run_pilot(manifest, root, clock=lambda: 1700000000.0)
    assert verify_pilot(root).ok
    return root


def _run_verifier(root: Path, work_dir: Path) -> subprocess.CompletedProcess[str]:
    # Run from a neutral directory with a bare environment so nothing but the
    # standard library is reachable: this exercises the zero-import guarantee.
    return subprocess.run(
        [sys.executable, "-I", str(VERIFIER), str(root)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
    )


def test_clean_pilot_root_matches(tmp_path: Path) -> None:
    root = _build_pilot_root(tmp_path)
    result = _run_verifier(root, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "MATCH" in result.stdout


def test_tampered_report_bytes_drift(tmp_path: Path) -> None:
    root = _build_pilot_root(tmp_path)
    report = root / "report.json"
    original = report.read_bytes()
    assert b"Evidence pilot" in original
    report.write_bytes(original.replace(b"Evidence pilot", b"Evidence Pilot", 1))
    result = _run_verifier(root, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DRIFT" in result.stdout


def test_missing_receipt_is_unverifiable(tmp_path: Path) -> None:
    root = _build_pilot_root(tmp_path)
    (root / "pilot-receipt.json").unlink()
    result = _run_verifier(root, tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "UNVERIFIABLE" in result.stdout


def test_verifier_imports_no_repo_package() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    assert "import gather" not in source
    assert "from gather" not in source
