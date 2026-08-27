#!/usr/bin/env python3
"""verify_pilot.py -- a zero-dependency, standalone verifier for a Gather pilot
output directory. Pure Python standard library, no gather import. A stranger
holding only a pilot root re-derives its integrity offline:

    python verify_pilot.py path/to/pilot-out

It re-reads manifest.json, report.json, report.html, and pilot-receipt.json,
recomputes the sha256 over each referenced artifact, re-derives the semantic
report digest and the archived-history chain, then compares every value to the
digests recorded in the receipt. It prints MATCH / DRIFT / UNVERIFIABLE and exits
0 only on MATCH, 1 on a digest or chain mismatch, 2 when an artifact is missing.

Scope (honest null): this vendored verifier re-derives the byte digests, the
semantic report digest, and the history root, the load-bearing seal. The full
in-tree "gather pilot verify" additionally re-renders report.html from the report
and checks byte equality; that clause needs the package renderer, so it is
reported UNVERIFIABLE here. The report.html byte digest is still re-derived, so a
flipped byte in report.html is caught.
"""
import hashlib
import json
import sys
from pathlib import Path

_ARTIFACTS = ("manifest.json", "report.json", "report.html", "pilot-receipt.json")
_EXIT = {"MATCH": 0, "DRIFT": 1, "UNVERIFIABLE": 2}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def _history_root(root):
    """Fold archived receipt bytes in name order into one chain root, or None on read error."""
    history = root / "history"
    if not history.is_dir():
        return ""
    previous = ""
    for path in sorted(history.glob("*-pilot-receipt.json")):
        body = _read_bytes(path)
        if body is None:
            return None
        previous = hashlib.sha256((previous + _sha256(body)).encode("ascii")).hexdigest()
    return previous


def verify(root):
    """Return (verdict, detail): MATCH, DRIFT, or UNVERIFIABLE for a pilot root."""
    bodies = {name: _read_bytes(root / name) for name in _ARTIFACTS}
    missing = [name for name, body in bodies.items() if body is None]
    if missing:
        return "UNVERIFIABLE", "artifact missing or unreadable: %s" % missing[0]
    try:
        receipt = json.loads(bodies["pilot-receipt.json"])
    except ValueError:
        return "UNVERIFIABLE", "pilot-receipt.json is not readable JSON"
    if not isinstance(receipt, dict):
        return "UNVERIFIABLE", "pilot-receipt.json is not a receipt object"

    for field, artifact in (
        ("manifest_sha256", "manifest.json"),
        ("report_json_sha256", "report.json"),
        ("report_html_sha256", "report.html"),
    ):
        if receipt.get(field) != _sha256(bodies[artifact]):
            return "DRIFT", "%s does not match the re-read %s bytes" % (field, artifact)

    try:
        report = json.loads(bodies["report.json"])
    except ValueError:
        return "DRIFT", "report.json is not the canonical JSON its digest was sealed over"
    recorded = report.get("report_digest")
    semantic = {key: value for key, value in report.items() if key != "report_digest"}
    computed = _sha256(_canonical(semantic))
    if recorded != computed or receipt.get("semantic_report_sha256") != computed:
        return "DRIFT", "report_digest does not re-derive from the report body"

    history = _history_root(root)
    if history is None:
        return "UNVERIFIABLE", "an archived history receipt is unreadable"
    if receipt.get("history_root_hash") != history:
        return "DRIFT", "history_root_hash does not re-derive from the archived receipts"

    return "MATCH", "seal re-derives: manifest, report, and receipt digests and history chain"


def main(argv):
    if not argv:
        print("usage: python verify_pilot.py <pilot-output-dir>", file=sys.stderr)
        return 2
    verdict, detail = verify(Path(argv[0]))
    print("%s  %s" % (verdict, detail))
    print("UNVERIFIABLE  report.html re-render equivalence is package-coupled; its sha256 is re-derived")
    return _EXIT[verdict]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
