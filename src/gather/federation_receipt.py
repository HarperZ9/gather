"""Two federation receipts that treat a decision as a claim surface, not a bare knob.

An adapter retry/backoff/fallback policy rule and an entity-resolution match both look
like configuration, but each asserts something about the world: this failure class is
retryable, this candidate IS this entity. The contracts here refuse the ways such an
assertion gets made without evidence. A policy rule with no provenance capture is not
evidence; an unknown failure class is not a known verdict; a superseded rule is not an
active one. An entity match with no named identifier path is a title guess, not an
identity join; ranked candidates out of confidence order are not a ranking; a promotion
to resolved on a fuzzy name match is not a resolution.

Both fold under the same digest seal the registry rows use (``gather.federation``): each
record is fingerprinted whole into its receipt ``sha256``, so editing any sealed field of
a witnessed policy rule or entity match breaks ``verify_digest`` exactly as content
tampering does. No source data ships here and nothing probes live: pure and deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from gather.digest import Digest, digest_of_receipts
from gather.federation import RegistryError
from gather.item import content_hash

# The closed failure-class vocabulary, each mapped to one TYPED verdict. A failure class
# is an observation about a route; the verdict is what the policy is allowed to conclude
# from it, never a free-form guess. 429 is throttling (the source is a lead, retry it),
# 403 is a policy wall (escalate access, do not hammer), 503 is a transient refusal
# (honor the retry-after, the source was not judged).
FAILURE_CLASS_VERDICTS: dict[str, str] = {
    "429": "retryable_source_lead",
    "403": "access_escalation",
    "503": "retry_after",
}

POLICY_RULE_FIELDS = ("rule", "source_capture_ref", "failure_class", "superseded")
ENTITY_MATCH_FIELDS = (
    "candidate_id", "identifier_path", "confidence", "evidence_refs", "exact_id_join")

_HEX = set("0123456789abcdef")

# the closed set of identifier paths that ARE an exact identity join: a
# registered id scheme, not a fuzzy title/name match. exact_id_join is derived
# from the path against this set, never trusted as a self-declared input flag.
_EXACT_ID_SCHEMES = frozenset({
    "doi", "orcid", "openalex", "isbn", "issn", "pmid", "pmcid",
    "arxiv", "ror", "wikidata", "grid", "isni",
})


def _path_is_exact_id(identifier_path: str) -> bool:
    scheme = identifier_path.split(":", 1)[0].strip().lower()
    return scheme in _EXACT_ID_SCHEMES


class PolicyRuleError(RegistryError):
    """A policy rule that violates the receipt contract: a typed, diagnosable rejection."""


class EntityResolutionError(RegistryError):
    """An entity match or ranking that violates the receipt contract: typed rejection."""


def _is_capture_ref(ref: object) -> bool:
    """A provenance capture ref is SHAPED like a content hash: 64 lowercase hex
    chars. Shape is necessary but NOT sufficient: it does not prove the ref
    addresses real captured bytes. Existence is checked separately, when a
    resolver is supplied, so a receipt never vouches for evidence it cannot see."""
    return isinstance(ref, str) and len(ref) == 64 and all(c in _HEX for c in ref)


CaptureResolver = "Callable[[str], bool]"


def _require_exists(ref: str, capture_exists, what: str, err) -> None:
    """When a resolver is supplied, refuse a ref that does not resolve to real
    captured bytes. No resolver means shape-only (the legacy contract), so this
    is additive: a caller that CAN check existence closes the gap."""
    if capture_exists is not None and not capture_exists(ref):
        raise err(f"{what} {ref!r} does not resolve to captured content: "
                  "shape is not existence, and a receipt must not vouch for "
                  "evidence it cannot see")


def verdict_for_failure_class(failure_class: str) -> str:
    """Map a failure class to its typed verdict; an unknown class is a typed rejection,
    never a best guess (guessing a verdict is exactly the laundering the gate refuses)."""
    verdict = FAILURE_CLASS_VERDICTS.get(failure_class)
    if verdict is None:
        raise PolicyRuleError(
            f"unknown failure class {failure_class!r}: the vocabulary is "
            f"{list(FAILURE_CLASS_VERDICTS)}")
    return verdict


def validate_policy_rule(rule: dict, *, capture_exists=None) -> dict:
    """Validate one policy rule and return it normalized with its derived verdict.

    The shape is closed: an extra key is how an unchecked field sneaks into a sealed
    record, so it is rejected. Three gates carry the finding: a rule with no provenance
    capture ref is rejected (a policy rule asserted without a source is not evidence); an
    unknown failure class is rejected; a rule marked superseded is rejected as active.
    """
    if not isinstance(rule, dict):
        raise PolicyRuleError(f"a policy rule must be an object, not {type(rule).__name__}")
    extra = sorted(set(rule) - set(POLICY_RULE_FIELDS))
    if extra:
        raise PolicyRuleError(f"unknown policy-rule field(s) {extra}: the shape is closed")
    missing = [k for k in POLICY_RULE_FIELDS if k not in rule]
    if missing:
        raise PolicyRuleError(f"policy rule missing required field(s) {missing}")
    if not isinstance(rule["rule"], str) or not rule["rule"]:
        raise PolicyRuleError("policy-rule field 'rule' must be a non-empty string")
    if not _is_capture_ref(rule["source_capture_ref"]):
        raise PolicyRuleError(
            "policy-rule source_capture_ref must be a content-hash capture ref; "
            "a rule asserted without a source is not evidence")
    _require_exists(rule["source_capture_ref"], capture_exists,
                    "policy-rule source_capture_ref", PolicyRuleError)
    verdict = verdict_for_failure_class(rule["failure_class"])
    if rule["superseded"] is not False:
        raise PolicyRuleError(
            "a rule marked superseded is not an active rule; it cannot be asserted")
    return {
        "rule": rule["rule"], "source_capture_ref": rule["source_capture_ref"],
        "failure_class": rule["failure_class"], "superseded": False, "verdict": verdict,
    }


def policy_rules(data: object) -> list:
    """Normalize a parsed policy document to its list of raw rules. Accepts a bare list
    or an object with a ``rules`` list; anything else is a typed rejection."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return data["rules"]
    raise PolicyRuleError('a policy document must be a list of rules or {"rules": [...]}')


def entity_candidates(data: object) -> list:
    """Normalize a parsed entity document to its list of raw candidates. Accepts a bare
    list or an object with a ``candidates`` list; anything else is a typed rejection."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return data["candidates"]
    raise EntityResolutionError(
        'an entity document must be a list of candidates or {"candidates": [...]}')


def _policy_rule_receipt(rule: dict) -> dict:
    """One digest receipt for one validated policy rule. The sha256 fingerprints the whole
    canonical rule (verdict included), so editing any sealed field breaks verify_digest."""
    clean = validate_policy_rule(rule)
    canon = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    return {
        "kind": "federation-policy-rule", "id": clean["rule"],
        "title": f"{clean['failure_class']} -> {clean['verdict']}",
        "source": "federation", "ref": clean["source_capture_ref"], "method": "policy",
        "sha256": content_hash(canon), "derived_from": [],
    }


def policy_rule_digest(rules: Iterable[dict]) -> Digest:
    """Fold validated policy rules into a witnessed digest under the federation seal
    machinery, the registry precedent: the claim rides inside the seal."""
    return digest_of_receipts([_policy_rule_receipt(r) for r in rules])


def _is_unit(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= x <= 1.0


def validate_entity_match(match: dict, *, capture_exists=None) -> dict:
    """Validate one entity-resolution candidate and return it normalized.

    The shape is closed. Gates: a match with no named identifier_path is rejected (a
    title or keyword match is not an identity join); confidence must be a unit-interval
    number; evidence_refs must be a non-empty list of content-hash refs (a match with no
    evidence is a guess). ``exact_id_join`` records whether the identifier_path is an
    exact-id join rather than a fuzzy/name match; promotion reads it, see resolve_entity.
    """
    if not isinstance(match, dict):
        raise EntityResolutionError(f"an entity match must be an object, not {type(match).__name__}")
    extra = sorted(set(match) - set(ENTITY_MATCH_FIELDS))
    if extra:
        raise EntityResolutionError(f"unknown entity-match field(s) {extra}: the shape is closed")
    missing = [k for k in ENTITY_MATCH_FIELDS if k not in match]
    if missing:
        raise EntityResolutionError(f"entity match missing required field(s) {missing}")
    if not isinstance(match["candidate_id"], str) or not match["candidate_id"]:
        raise EntityResolutionError("entity-match candidate_id must be a non-empty string")
    if not isinstance(match["identifier_path"], str) or not match["identifier_path"]:
        raise EntityResolutionError(
            "entity-match identifier_path must be a named join key; "
            "a title or keyword match is not an identity join")
    if not _is_unit(match["confidence"]):
        raise EntityResolutionError("entity-match confidence must be a number in [0, 1]")
    refs = match["evidence_refs"]
    if not isinstance(refs, list) or not refs or not all(_is_capture_ref(r) for r in refs):
        raise EntityResolutionError(
            "entity-match evidence_refs must be a non-empty list of content-hash refs")
    for r in refs:
        _require_exists(r, capture_exists, "entity-match evidence_ref", EntityResolutionError)
    if not isinstance(match["exact_id_join"], bool):
        raise EntityResolutionError("entity-match exact_id_join must be a boolean")
    # exact_id_join is DERIVED from the identifier path, not trusted from the
    # input: a self-declared True on a fuzzy/name path is a claim the path does
    # not support, and promotion would launder a name match into an identity.
    if match["exact_id_join"] and not _path_is_exact_id(match["identifier_path"]):
        raise EntityResolutionError(
            f"exact-id join claimed on identifier_path {match['identifier_path']!r}, "
            f"which is not a registered exact-id scheme {sorted(_EXACT_ID_SCHEMES)}; "
            "a self-declared join the path does not support is refused")
    return {k: match[k] for k in ENTITY_MATCH_FIELDS}


def resolve_entity(candidates: Iterable[dict]) -> dict:
    """Rank validated candidates and, when justified, promote the top one to resolved.

    Gates: there must be at least one candidate; the candidates must already be ordered
    by descending confidence (an out-of-order list is not a ranking, so it is rejected,
    never silently re-sorted); and a promotion to resolved requires the top candidate to
    be an exact-id join, not a fuzzy/name match. The receipt names what resolved it.
    """
    clean = [validate_entity_match(c) for c in candidates]
    if not clean:
        raise EntityResolutionError("no candidate to resolve: an empty list is not a match")
    confidences = [c["confidence"] for c in clean]
    if confidences != sorted(confidences, reverse=True):
        raise EntityResolutionError(
            "ranked candidates must be ordered by confidence, descending")
    top = clean[0]
    if not top["exact_id_join"]:
        raise EntityResolutionError(
            "promotion to resolved requires an exact-id join at the top, "
            "not a fuzzy/name match")
    return {
        "resolved": top["candidate_id"], "identifier_path": top["identifier_path"],
        "confidence": top["confidence"], "candidates": clean,
    }


def _entity_match_receipt(match: dict) -> dict:
    """One digest receipt for one validated entity match. The sha256 fingerprints the whole
    canonical candidate, so editing any sealed field breaks verify_digest."""
    clean = validate_entity_match(match)
    canon = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    return {
        "kind": "federation-entity-match", "id": clean["candidate_id"],
        "title": f"{clean['identifier_path']}: {clean['candidate_id']}",
        "source": "federation", "ref": clean["evidence_refs"][0], "method": "entity",
        "sha256": content_hash(canon), "derived_from": [],
    }


def entity_match_digest(matches: Iterable[dict]) -> Digest:
    """Fold validated entity matches into a witnessed digest under the federation seal
    machinery. Candidate order does not change the seal; any field edit after witnessing does."""
    return digest_of_receipts([_entity_match_receipt(m) for m in matches])
