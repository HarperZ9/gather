"""The adapter policy compiler and the claims guard for the federation registry.

``compile_plan`` is a pure function from an access-policy token to its deterministic
capture plan: what to do, in what order, whether a live probe is permitted, and what
the plan must never do. ``guard_claim`` is the whitelist over claims: a claim stands
only on an allowed basis, the known-bad patterns are refused by name, and everything
else is denied by default. Both are machinery only; nothing here touches the network.
"""

from __future__ import annotations

import copy

from gather.federation import ACCESS_TOKENS, ForbiddenClaim, UnknownAccessToken

_NEVER_COVERAGE = "present registry size as coverage"

# One deterministic capture plan per access token. steps are ordered; forbids are the
# standing refusals the plan carries with it. Every plan forbids the coverage claim,
# because no capture posture makes a row count mean world coverage.
_PLANS: dict[str, dict] = {
    "open": {
        "action": "capture",
        "steps": ["capture immediately", "record the body hash in the receipt"],
        "live_probe": True,
        "forbids": [_NEVER_COVERAGE],
    },
    "key_required": {
        "action": "record_lead",
        "steps": ["record the source lead", "capture the public docs",
                  "record the credential requirement for the operator"],
        "live_probe": False,
        "forbids": ["attempt hidden credentials",
                    "claim availability without a verified capture", _NEVER_COVERAGE],
    },
    "rate_limited": {
        "action": "retry_gated_capture",
        "steps": ["record the retry policy", "capture within the recorded retry policy",
                  "record the body hash in the receipt"],
        "live_probe": True,
        "forbids": ["probe live before the retry policy is recorded", _NEVER_COVERAGE],
    },
    "restricted_or_registered": {
        "action": "docs_then_admission",
        "steps": ["capture the public docs", "record an admission-gated future task"],
        "live_probe": False,
        "forbids": ["claim availability without a verified capture", _NEVER_COVERAGE],
    },
    "endpoint_alias_needed": {
        "action": "alias_check",
        "steps": ["record the stale endpoint", "record the alternate endpoint",
                  "capture through the recorded alternate"],
        "live_probe": True,
        "forbids": ["declare source absence before an alternate endpoint is recorded",
                    _NEVER_COVERAGE],
    },
    "source_lead_only": {
        "action": "catalog_only",
        "steps": ["catalog the source lead"],
        "live_probe": False,
        "forbids": ["claim availability", "claim coverage", _NEVER_COVERAGE],
    },
    "account_required": {
        "action": "account_gated",
        "steps": ["record the account requirement", "capture the public docs",
                  "record an admission-gated future task"],
        "live_probe": False,
        "forbids": ["create or borrow an account", "attempt hidden credentials",
                    "claim availability without a verified capture", _NEVER_COVERAGE],
    },
}

assert set(_PLANS) == set(ACCESS_TOKENS), "every access token compiles to exactly one plan"

# The known-bad claim patterns, refused by name. Each is a way a registry fact gets
# dressed up as evidence; each is a negative fixture the test suite must see rejected.
FORBIDDEN_CLAIMS: dict[tuple[str, str], str] = {
    ("coverage", "registry_size"): "source_count_as_world_coverage",
    ("availability", "registry_listing"): "registry_listing_as_endpoint_availability",
    ("full_text", "metadata"): "metadata_as_full_text",
    ("availability", "access_token"): "closed_key_source_as_available",
    ("match", "empty_capture"): "empty_capture_as_match",
    ("absence", "route_failure"): "route_failure_as_source_absence",
}

# The whitelist: the only bases a claim may stand on. Availability, match, and full-text
# claims need a verified capture; an absence claim needs the alternates exhausted first.
# Coverage has no allowed basis here at all: nothing in registry machinery grounds it.
ALLOWED_CLAIMS: frozenset[tuple[str, str]] = frozenset({
    ("availability", "verified_capture"),
    ("match", "verified_capture"),
    ("full_text", "verified_capture"),
    ("absence", "exhausted_alternates"),
})


def compile_plan(access: str) -> dict:
    """Compile an access-policy token into its deterministic capture plan.

    Pure: the same token always yields the same plan, and each call returns a fresh
    copy (a caller mutating its plan cannot poison the next). A token outside the
    closed vocabulary is a typed rejection, never a best guess.
    """
    if access not in _PLANS:
        raise UnknownAccessToken(
            f"unknown access token {access!r}: the vocabulary is {list(ACCESS_TOKENS)}")
    return {"access": access, **copy.deepcopy(_PLANS[access])}


def guard_claim(claim: str, basis: str) -> dict:
    """Admit a claim only on an allowed basis; refuse the known-bad patterns by name.

    Default deny: a (claim, basis) pair in ``FORBIDDEN_CLAIMS`` raises ForbiddenClaim
    carrying the pattern's name, and a pair outside ``ALLOWED_CLAIMS`` raises too, so
    a novel laundering route fails closed rather than open. The return value for an
    admitted claim is the normalized record, explicit about what grounded it.
    """
    name = FORBIDDEN_CLAIMS.get((claim, basis))
    if name is not None:
        raise ForbiddenClaim(
            f"{name}: a {basis!r} basis can never ground a {claim!r} claim")
    if (claim, basis) not in ALLOWED_CLAIMS:
        raise ForbiddenClaim(
            f"claim {claim!r} on basis {basis!r} is not in the allowed table; "
            f"the guard denies by default")
    return {"claim": claim, "basis": basis, "allowed": True}
