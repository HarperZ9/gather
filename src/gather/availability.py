from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Protocol, TypeGuard

from gather.digest import Digest, digest_of_receipts
from gather.item import content_hash

# Witnessed statuses: what an availability check RECORDS on a rung. A check never records
# "unknown"; the absence of a rung is what unknown looks like, and it is reported as such.
AVAILABLE = "AVAILABLE"      # the source answered; the rung's sha256 fingerprints what it served
UNAVAILABLE = "UNAVAILABLE"  # the source did not answer; nothing was observed, nothing is bound

# Derived outcomes: what re-verification REPORTS. An outcome is computed from the rung's
# machine-checkable binding, never taken from an author-controlled string. AVAILABLE and
# UNAVAILABLE reappear here when the rung's claim stands; the other two are derived only.
CHANGED = "CHANGED"          # the rung says available but its binding differs from the receipt:
                             # the source answered with content OTHER than what was witnessed
UNWITNESSED = "UNWITNESSED"  # no rung, or a rung too malformed to make a claim (legacy records)

_HEX = set("0123456789abcdef")

Probe = Callable[[dict], "str | None"]  # catalog row in -> the source's current text, or None


class ReadsBodies(Protocol):
    """What the stored probe needs from a corpus: read a body by its content hash."""

    def read_text(self, sha256: str) -> str: ...


def _is_hash(s: object) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in _HEX for c in s)


def availability_rung(*, status: str, checked_at: float, sha256: str) -> dict:
    """Build one availability rung: ``{status, checked_at, sha256}``.

    The binding rule is enforced here: an AVAILABLE rung must bind the content hash of what
    was actually observed (a claim with no evidence is refused), and an UNAVAILABLE rung must
    bind nothing (an unavailability claim that also carries an observed hash contradicts
    itself). Folded into the digest seal by ``digest_of_receipts``, so once witnessed the rung
    cannot be edited without breaking the seal.
    """
    if status not in (AVAILABLE, UNAVAILABLE):
        raise ValueError(f"availability status must be {AVAILABLE} or {UNAVAILABLE}, not {status!r}")
    if status == AVAILABLE and not _is_hash(sha256):
        raise ValueError("an AVAILABLE rung must bind the observed content hash")
    if status == UNAVAILABLE and sha256 != "":
        raise ValueError("an UNAVAILABLE rung observed nothing, so it must bind no hash")
    return {"status": status, "checked_at": float(checked_at), "sha256": sha256}


def _well_formed(av: object) -> TypeGuard[dict]:
    """A rung makes a claim only when its shape and binding rule both hold."""
    if not isinstance(av, dict) or isinstance(av.get("checked_at"), bool):
        return False
    if not isinstance(av.get("checked_at"), (int, float)):
        return False
    if av.get("status") == AVAILABLE:
        return _is_hash(av.get("sha256"))
    return av.get("status") == UNAVAILABLE and av.get("sha256") == ""


def assess_availability(receipt: dict) -> str:
    """Derive the typed availability outcome for one receipt (a digest receipt or catalog row).

    The rules never trust the rung's status string alone: the AVAILABLE outcome is gated on the
    rung's content-hash binding matching the receipt's own sha256. So a record whose rung claims
    available for a hash-mismatched source is rejected as CHANGED (the source answered, but not
    with the witnessed content), which re-verification distinguishes from UNAVAILABLE (the
    source did not answer at all). A receipt with no rung, or a malformed one, makes no claim:
    UNWITNESSED, never AVAILABLE. Tampering with a witnessed rung is the seal's business
    (``verify_digest``); this function reads what the rung honestly says.
    """
    av = receipt.get("availability")
    if not _well_formed(av):
        return UNWITNESSED
    if av["status"] == UNAVAILABLE:
        return UNAVAILABLE
    return AVAILABLE if av["sha256"] == receipt.get("sha256") else CHANGED


def check_receipts(rows: Iterable[dict], probe: Probe, *, clock: Callable[[], float] = time.time) -> list[dict]:
    """Check each row's source through ``probe`` and return the rows with a fresh rung attached.

    The probe answers "what does this source serve right now": text, or None if it cannot be
    reached. A probe that raises is recorded as UNAVAILABLE (an unreachable source is an
    observation, not a crash; the probe is an external edge, so it must not abort the check).
    An answering source is recorded AVAILABLE with the hash of what it served, whether or not
    that matches the receipt; the honest divergence is what ``assess_availability`` reads as
    CHANGED. The clock is injected, so a check is replayable in tests.
    """
    checked = []
    for row in rows:
        now = float(clock())
        try:
            text = probe(row)
        except Exception:  # noqa: BLE001 - a probe is an untrusted edge; failure is the observation
            text = None
        if text is None:
            rung = availability_rung(status=UNAVAILABLE, checked_at=now, sha256="")
        else:
            rung = availability_rung(status=AVAILABLE, checked_at=now, sha256=content_hash(text))
        checked.append({**row, "availability": rung})
    return checked


def witness_availability(rows: Iterable[dict], probe: Probe, *,
                         clock: Callable[[], float] = time.time) -> Digest:
    """Check every row and seal the result: the corpus digest with each receipt's availability
    rung folded into the seal. After this, editing any rung (its status, its checked_at, or its
    hash binding) breaks ``verify_digest``, so availability cannot be rewritten after witnessing.
    Receipts keep the input row order; the seal is order-independent as always."""
    return digest_of_receipts(check_receipts(rows, probe, clock=clock))


def stored_probe(corpus: ReadsBodies) -> Probe:
    """The standing default probe: read each row's body from the corpus's own object store
    (Gather stands alone; a live re-fetch probe plugs in through the same seam). A missing body
    reads as the source being unavailable; a body corrupted in place hashes differently, so the
    check reports it CHANGED. A row whose sha cannot address an object at all reads as
    unavailable too."""
    def probe(row: dict) -> str | None:
        sha = row.get("sha256")
        if not isinstance(sha, str) or not sha:
            return None
        try:
            return corpus.read_text(sha)
        except (OSError, ValueError):
            return None
    return probe
