from __future__ import annotations

import json
import subprocess
from typing import Protocol

from gather.item import Item


class ProvenanceProvider(Protocol):
    """Composes an EXTERNAL origin verdict for an item, beyond Gather's own content receipt.

    Gather's receipt answers "is this the content that was obtained, unaltered" (the sha256). An
    external provenance organ answers a different question: where did the content originate, is it
    forged, is it a re-encode of something else. This seam lets such an organ (provenance-sensorium)
    attach its verdict to each item before a run is witnessed, so the run records not just what was
    gathered but each item's origin verdict. ``origin`` returns a small dict verdict; an empty dict
    means no external check was made. The default is the Null provider, so Gather stands alone.
    """

    def origin(self, item: Item) -> dict: ...


class NullProvenanceProvider:
    """The standing default: no external origin check (Gather stands alone). Always returns ``{}``."""

    def origin(self, item: Item) -> dict:
        return {}


class SubprocessProvenanceProvider:
    """The real edge: shells to an external provenance organ for an item's origin verdict.

    Sends a JSON request ``{"source", "ref", "method", "sha256"}`` on the tool's STDIN (never the
    argv, so a gathered ref cannot be parsed as a flag) and parses a JSON verdict from its stdout.
    The command is operator-configured, e.g. ``["python", "-m", "provenance", "check", "--json"]``.
    A non-zero exit or unparseable output yields ``{"error": ...}`` rather than raising, so one
    unprovable item does not abort a whole run. fetch-time only; needs the tool on PATH.
    """

    def __init__(self, command: list[str], *, timeout: float = 60.0) -> None:
        if not command:
            raise ValueError("SubprocessProvenanceProvider needs a non-empty command")
        self._command = list(command)
        self._timeout = timeout

    def origin(self, item: Item) -> dict:
        p = item.provenance
        request = json.dumps(
            {"source": p.source, "ref": p.ref, "method": p.method, "sha256": p.sha256},
            sort_keys=True,
        )
        try:
            proc = subprocess.run(
                self._command, input=request.encode("utf-8"), capture_output=True, timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": f"provenance tool did not run: {str(exc)[:120]}"}
        if proc.returncode != 0:
            return {"error": f"provenance tool failed: {proc.stderr.decode('utf-8', 'replace').strip()[:120]}"}
        out = proc.stdout.decode("utf-8", "replace").strip()
        try:
            verdict = json.loads(out)
        except json.JSONDecodeError:
            return {"error": "provenance tool output was not JSON"}
        return verdict if isinstance(verdict, dict) else {"verdict": verdict}
