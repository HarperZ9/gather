"""The source-federation registry contract.

A registry names the sources a research corpus COULD draw from: what system, which
family and domain, how it is reached, and under what access policy. The contract here
is deliberately closed: a row has exactly nine fields, the access-policy vocabulary is
fixed, and the capture-status vocabulary a probe may record is fixed. A registry row
is a catalog fact and nothing more. It never stands in for coverage, availability, or
content; those claims need evidence, and the guard in ``gather.federation_policy``
refuses the known ways a listing gets dressed up as one.

Registry receipts fold under the existing digest seal (``gather.digest``), the same
machinery the availability rung uses: each row is fingerprinted whole, so editing any
field of a sealed registry snapshot breaks ``verify_digest``.

No source data ships here and nothing probes live: this module is the machinery and
its vocabulary, pure and deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from gather.digest import Digest, digest_of_receipts
from gather.item import content_hash

# The closed access-policy vocabulary: how a source may be reached, which is a statement
# about POLICY, never about availability. gather.federation_policy compiles each token
# into its deterministic capture plan.
ACCESS_TOKENS = (
    "open",                      # publicly reachable; capture immediately and hash the body
    "key_required",              # needs a credential; record the lead, never hunt for keys
    "rate_limited",              # reachable but throttled; record the retry policy first
    "restricted_or_registered",  # gated behind registration; public docs now, admission later
    "endpoint_alias_needed",     # the canonical endpoint is stale; record the alternate first
    "source_lead_only",          # known to exist; catalog it, claim nothing
    "account_required",          # needs an operator-owned account; never create or borrow one
)

# The closed capture-status vocabulary: what one probe of one source may record.
# A probe records an observation, never a verdict about the source.
CAPTURE_STATUSES = (
    "GATHER_VERIFIED",                # a capture landed and its body hash was witnessed
    "GATHER_EMPTY_WARNING",           # the route answered but the capture carried nothing
    "GATHER_DROPPED_WARNING",         # items were captured but dropped before witnessing
    "HTTP_503_WARNING",               # the route refused service; says nothing about the source
    "HTTP_400_QUERY_SHAPE_WARNING",   # the query shape was rejected; the source was not judged
    "HTTP_429_RATE_LIMIT_WARNING",    # throttled; an access observation, not an absence
)

# Derived evidence statuses: what join() may REPORT for a source, computed from its
# capture statuses. Never recorded by a probe directly.
GATHER_VERIFIED = "GATHER_VERIFIED"
GATHER_VERIFIED_WITH_WARNINGS = "GATHER_VERIFIED_WITH_WARNINGS"
SOURCE_LEAD_ONLY = "SOURCE_LEAD_ONLY"

ROW_FIELDS = ("id", "system", "family", "domain", "access", "adapter", "url", "scope", "priority")
PRIORITIES = ("high", "medium", "low")

_SLUG_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class RegistryError(ValueError):
    """A registry input that violates the contract: a typed, diagnosable rejection."""


class UnknownAccessToken(RegistryError):
    """An access token outside the closed vocabulary. The vocabulary is the contract;
    an unrecognized policy is refused, never guessed at."""


class UnknownCaptureStatus(RegistryError):
    """A capture status outside the closed vocabulary. join() refuses to derive
    evidence from a status it cannot read."""


class ForbiddenClaim(ValueError):
    """A claim pattern the federation contract exists to refuse (for example presenting
    registry size as coverage). Raised by ``gather.federation_policy.guard_claim``."""


def _is_slug(s: object) -> bool:
    return (isinstance(s, str) and bool(s) and not s.startswith("-")
            and all(c in _SLUG_CHARS for c in s))


def validate_row(row: dict) -> dict:
    """Validate one registry row against the closed contract and return it normalized.

    The shape is closed both ways: every field in ``ROW_FIELDS`` must be present and a
    key outside them is rejected (an extra field is how an unchecked claim sneaks into a
    sealed record). The id must be a stable lowercase slug, the access token and priority
    must come from their closed vocabularies, and every other field must be a non-empty
    string. Rejections are typed and name the offending field.
    """
    if not isinstance(row, dict):
        raise RegistryError(f"a registry row must be an object, not {type(row).__name__}")
    extra = sorted(set(row) - set(ROW_FIELDS))
    if extra:
        raise RegistryError(f"unknown registry field(s) {extra}: the row shape is closed")
    missing = [k for k in ROW_FIELDS if k not in row]
    if missing:
        raise RegistryError(f"registry row missing required field(s) {missing}")
    if not _is_slug(row["id"]):
        raise RegistryError(f"registry id must be a stable lowercase slug, not {row['id']!r}")
    if row["access"] not in ACCESS_TOKENS:
        raise UnknownAccessToken(
            f"unknown access token {row['access']!r}: the vocabulary is {list(ACCESS_TOKENS)}")
    if row["priority"] not in PRIORITIES:
        raise RegistryError(f"priority must be one of {list(PRIORITIES)}, not {row['priority']!r}")
    for key in ("system", "family", "domain", "adapter", "url", "scope"):
        if not isinstance(row[key], str) or not row[key]:
            raise RegistryError(f"registry field {key!r} must be a non-empty string")
    return {k: row[k] for k in ROW_FIELDS}


def validate_registry(rows: Iterable[dict]) -> list[dict]:
    """Validate every row and refuse duplicate ids (a registry is a set of stable slugs;
    two rows under one id would let a later edit hide behind an earlier seal)."""
    out = []
    seen: set[str] = set()
    for row in rows:
        clean = validate_row(row)
        if clean["id"] in seen:
            raise RegistryError(f"duplicate registry id {clean['id']!r}")
        seen.add(clean["id"])
        out.append(clean)
    return out


def registry_rows(data: object) -> list:
    """Normalize a parsed registry document to its list of raw rows. Accepts a bare list
    or an object with a ``sources`` list; anything else is a typed rejection."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("sources"), list):
        return data["sources"]
    raise RegistryError('a registry document must be a list of rows or {"sources": [...]}')


def join(statuses: Iterable[str]) -> str:
    """Derive one evidence status for a source from the set of its capture statuses.

    The rules, in order: GATHER_VERIFIED present alongside any other distinct status
    reports GATHER_VERIFIED_WITH_WARNINGS (a landed capture does not launder its
    warnings); only GATHER_VERIFIED reports GATHER_VERIFIED; captures with no verified
    landing report a deterministic REPRESENTATIVE warning (the sorted-first distinct
    status) whose single job is to name THAT a warning occurred, not to rank severity
    (the warnings are not ordered by severity, so a single derived status cannot claim
    a 'worst'); and no captures at all reports SOURCE_LEAD_ONLY, because a source nobody
    probed has exactly the evidence standing of a lead. A status outside the closed
    vocabulary is a typed rejection, never folded in.
    """
    seen: set[str] = set()
    for status in statuses:
        if status not in CAPTURE_STATUSES:
            raise UnknownCaptureStatus(
                f"unknown capture status {status!r}: the vocabulary is {list(CAPTURE_STATUSES)}")
        seen.add(status)
    if not seen:
        return SOURCE_LEAD_ONLY
    if GATHER_VERIFIED in seen:
        return GATHER_VERIFIED_WITH_WARNINGS if len(seen) > 1 else GATHER_VERIFIED
    # a deterministic representative warning, NOT a severity ranking: the
    # warnings carry no severity order, so this names that a warning occurred
    return sorted(seen)[0]


def registry_receipt(row: dict) -> dict:
    """One digest receipt for one validated registry row.

    The sha256 fingerprints the whole canonical row, so the seal covers every field:
    flipping an access token, repointing a url, or promoting a priority in a sealed
    snapshot breaks ``verify_digest`` exactly as content tampering does. The method is
    ``registry``: this receipt witnesses what the registry SAID, never what any source
    served.
    """
    clean = validate_row(row)
    canon = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    return {
        "kind": "federation-source", "id": clean["id"],
        "title": f"{clean['system']}: {clean['family']}",
        "source": "federation", "ref": clean["url"], "method": "registry",
        "sha256": content_hash(canon), "derived_from": [],
    }


def registry_digest(rows: Iterable[dict]) -> Digest:
    """Fold a registry snapshot into a witnessed digest under the corpus seal machinery
    (the availability-rung precedent: the claim rides inside the seal). Row order does
    not change the seal; any row edit after witnessing does."""
    return digest_of_receipts([registry_receipt(r) for r in validate_registry(rows)])
