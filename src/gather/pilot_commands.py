"""CLI command adapters for the pilot engine.

Thin wrappers over the public pilot functions. Each command emits a JSON result
on --json, returns a typed exit code, and surfaces boundary refusals as short
diagnostics without a traceback.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gather.pilot import (
    PilotRefusal,
    PilotResult,
    refresh_pilot,
    run_pilot,
    verify_pilot,
)
from gather.pilot_bundle import create_pilot_bundle, verify_pilot_bundle
from gather.pilot_manifest import (
    PilotManifest,
    load_pilot_manifest,
    validate_pilot_manifest,
)


def pilot_exit_code(manifest: PilotManifest, result: PilotResult) -> int:
    """0 when every required source captured; 1 otherwise."""
    required = {
        source.id
        for mission in manifest.missions
        for source in mission.sources
        if source.required
    }
    return (
        0
        if all(
            outcome.source_id not in required or outcome.status == "CAPTURED"
            for outcome in result.source_outcomes
        )
        else 1
    )


def _emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_pilot_run(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))
    try:
        manifest = load_pilot_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"manifest refused: {_short(str(exc))}", file=sys.stderr)
        return 2
    try:
        result = run_pilot(manifest, Path(args.output))
    except PilotRefusal as exc:
        print(f"pilot refused: {_short(str(exc))}", file=sys.stderr)
        return 1
    _emit(
        {
            "action": "run",
            "manifest_digest": result.manifest_sha256,
            "source_outcomes": [o.to_dict() for o in result.source_outcomes],
            "corpus_verified": result.corpus_verified,
        },
        as_json,
    )
    return pilot_exit_code(manifest, result)


def cmd_pilot_refresh(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))
    try:
        result = refresh_pilot(Path(args.output_dir))
    except PilotRefusal as exc:
        print(f"refresh refused: {_short(str(exc))}", file=sys.stderr)
        return 1
    _emit(
        {
            "action": "refresh",
            "monitor_report": result.monitor_report,
        },
        as_json,
    )
    return 0


def cmd_pilot_verify(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))
    verification = verify_pilot(Path(args.output_dir))
    _emit(
        {
            "action": "verify",
            "ok": verification.ok,
            "checks": verification.to_dict(),
        },
        as_json,
    )
    return 0 if verification.ok else 1


def cmd_pilot_bundle(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))
    visibility = args.visibility
    include_private = bool(getattr(args, "include_private_evidence", False))
    try:
        receipt = create_pilot_bundle(
            Path(args.output_dir),
            Path(args.bundle_output),
            visibility=visibility,
            include_private_evidence=include_private,
        )
    except PilotRefusal as exc:
        print(f"bundle refused: {_short(str(exc))}", file=sys.stderr)
        return 1
    if as_json:
        _emit(
            {
                "action": "bundle",
                "visibility": receipt.visibility,
                "bundle_digest": receipt.bundle_digest,
                "verified": verify_pilot_bundle(Path(args.bundle_output)).ok,
            },
            as_json,
        )
    return 0


def _short(text: str, limit: int = 240) -> str:
    return " ".join(text.split())[:limit]


# validate_pilot_manifest is re-exported for callers that build manifests inline.
__all__ = [
    "cmd_pilot_bundle",
    "cmd_pilot_refresh",
    "cmd_pilot_run",
    "cmd_pilot_verify",
    "pilot_exit_code",
    "validate_pilot_manifest",
]
