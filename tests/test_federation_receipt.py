import dataclasses

import pytest

from gather.digest import verify_digest
from gather.federation import RegistryError
from gather.federation_receipt import (
    FAILURE_CLASS_VERDICTS,
    EntityResolutionError,
    PolicyRuleError,
    entity_match_digest,
    policy_rule_digest,
    resolve_entity,
    validate_entity_match,
    validate_policy_rule,
    verdict_for_failure_class,
)

_CAP = "a" * 64


# --- POLICY-AS-RECEIPT (dogfood 0146) fixtures ---


def _rule(**over):
    rule = {
        "rule": "retry-on-throttle",
        "source_capture_ref": _CAP,
        "failure_class": "429",
        "superseded": False,
    }
    rule.update(over)
    return rule


def _match(**over):
    match = {
        "candidate_id": "ror-052gg0110",
        "identifier_path": "ror",
        "confidence": 0.98,
        "evidence_refs": [_CAP],
        "exact_id_join": True,
    }
    match.update(over)
    return match


# --- the policy rule contract: a rule is a claim surface, not a bare knob ---


def test_a_valid_policy_rule_normalizes_and_carries_its_typed_verdict():
    out = validate_policy_rule(_rule())
    assert out["rule"] == "retry-on-throttle"
    assert out["source_capture_ref"] == _CAP
    assert out["failure_class"] == "429"
    assert out["verdict"] == "retryable_source_lead"


def test_every_known_failure_class_maps_to_a_typed_verdict():
    assert FAILURE_CLASS_VERDICTS["429"] == "retryable_source_lead"
    assert FAILURE_CLASS_VERDICTS["403"] == "access_escalation"
    assert FAILURE_CLASS_VERDICTS["503"] == "retry_after"
    for cls in FAILURE_CLASS_VERDICTS:
        assert verdict_for_failure_class(cls) == FAILURE_CLASS_VERDICTS[cls]


# gate 1: a rule with no provenance capture is not evidence


def test_a_rule_with_no_provenance_capture_is_rejected():
    rule = _rule()
    del rule["source_capture_ref"]
    with pytest.raises(PolicyRuleError, match="source_capture_ref"):
        validate_policy_rule(rule)


def test_a_rule_with_an_empty_provenance_capture_is_rejected():
    with pytest.raises(PolicyRuleError, match="source_capture_ref"):
        validate_policy_rule(_rule(source_capture_ref=""))


def test_a_rule_with_a_non_hex_provenance_capture_is_rejected():
    with pytest.raises(PolicyRuleError, match="source_capture_ref"):
        validate_policy_rule(_rule(source_capture_ref="not-a-hash"))


# gate 2: an unknown failure class is refused, never guessed


def test_an_unknown_failure_class_is_a_typed_rejection():
    with pytest.raises(PolicyRuleError, match="probably_transient"):
        validate_policy_rule(_rule(failure_class="probably_transient"))


def test_verdict_for_an_unknown_failure_class_is_a_typed_rejection():
    with pytest.raises(PolicyRuleError, match="teapot"):
        verdict_for_failure_class("teapot")


# gate 3: a rule marked superseded is not an active rule


def test_a_superseded_rule_is_rejected_as_active():
    with pytest.raises(PolicyRuleError, match="superseded"):
        validate_policy_rule(_rule(superseded=True))


def test_the_positive_rule_is_active_when_not_superseded():
    assert validate_policy_rule(_rule(superseded=False))["superseded"] is False
    assert validate_policy_rule(_rule())["superseded"] is False


def test_an_unknown_extra_rule_field_is_rejected():
    with pytest.raises(PolicyRuleError, match="coverage"):
        validate_policy_rule({**_rule(), "coverage": "always"})


# --- policy rules fold under the federation seal ---


def test_policy_rule_digest_seals_every_rule_and_verifies():
    d = policy_rule_digest([_rule(), _rule(rule="escalate-on-forbidden", failure_class="403")])
    assert len(d.receipts) == 2
    assert verify_digest(d) is True
    for r in d.receipts:
        assert r["kind"] == "federation-policy-rule"
        assert r["source"] == "federation"
        assert r["method"] == "policy"
        assert len(r["sha256"]) == 64


def test_editing_a_sealed_policy_rule_receipt_breaks_the_seal():
    d = policy_rule_digest([_rule()])
    edited = dataclasses.replace(
        d, receipts=({**d.receipts[0], "sha256": "b" * 64},))
    assert verify_digest(edited) is False


def test_two_rules_differing_only_in_failure_class_seal_differently():
    a = policy_rule_digest([_rule(failure_class="429")]).seal
    b = policy_rule_digest([_rule(failure_class="503")]).seal
    assert a != b


# --- ENTITY-RESOLUTION (dogfood 0147) contract ---


def test_a_valid_entity_match_normalizes_to_the_contract_fields():
    out = validate_entity_match(_match())
    assert out["candidate_id"] == "ror-052gg0110"
    assert out["identifier_path"] == "ror"
    assert out["confidence"] == 0.98
    assert out["evidence_refs"] == [_CAP]


# gate 1: a title/keyword match is not an identity join


def test_a_match_with_no_named_identifier_path_is_rejected():
    match = _match()
    del match["identifier_path"]
    with pytest.raises(EntityResolutionError, match="identifier_path"):
        validate_entity_match(match)


def test_a_match_with_an_empty_identifier_path_is_rejected():
    with pytest.raises(EntityResolutionError, match="identifier_path"):
        validate_entity_match(_match(identifier_path=""))


def test_a_match_with_no_evidence_refs_is_rejected():
    with pytest.raises(EntityResolutionError, match="evidence"):
        validate_entity_match(_match(evidence_refs=[]))


def test_a_match_with_a_non_hex_evidence_ref_is_rejected():
    with pytest.raises(EntityResolutionError, match="evidence"):
        validate_entity_match(_match(evidence_refs=["not-a-hash"]))


def test_confidence_outside_the_unit_interval_is_rejected():
    with pytest.raises(EntityResolutionError, match="confidence"):
        validate_entity_match(_match(confidence=1.5))
    with pytest.raises(EntityResolutionError, match="confidence"):
        validate_entity_match(_match(confidence=-0.1))


# gate 2: ranked candidates must be ordered by confidence


def test_ranked_candidates_out_of_confidence_order_are_rejected():
    lo = _match(candidate_id="ror-lo", confidence=0.4)
    hi = _match(candidate_id="ror-hi", confidence=0.9)
    with pytest.raises(EntityResolutionError, match="ordered by confidence"):
        resolve_entity([lo, hi])


def test_ranked_candidates_in_confidence_order_resolve():
    hi = _match(candidate_id="ror-hi", confidence=0.98)
    lo = _match(candidate_id="ror-lo", confidence=0.4, exact_id_join=False,
                identifier_path="name")
    receipt = resolve_entity([hi, lo])
    assert receipt["resolved"] == "ror-hi"
    assert [c["candidate_id"] for c in receipt["candidates"]] == ["ror-hi", "ror-lo"]


# gate 3: promotion to resolved requires an exact-id join at the top


def test_a_top_candidate_that_is_a_fuzzy_name_match_is_not_promoted():
    fuzzy = _match(candidate_id="name-top", identifier_path="name",
                   exact_id_join=False, confidence=0.99)
    with pytest.raises(EntityResolutionError, match="exact-id"):
        resolve_entity([fuzzy])


def test_a_single_exact_id_candidate_is_promoted():
    receipt = resolve_entity([_match()])
    assert receipt["resolved"] == "ror-052gg0110"
    assert receipt["identifier_path"] == "ror"


def test_an_empty_candidate_list_resolves_to_nothing():
    with pytest.raises(EntityResolutionError, match="no candidate"):
        resolve_entity([])


# --- entity matches fold under the federation seal ---


def test_entity_match_digest_seals_every_candidate_and_verifies():
    d = entity_match_digest([_match(), _match(candidate_id="ror-other", confidence=0.5)])
    assert len(d.receipts) == 2
    assert verify_digest(d) is True
    for r in d.receipts:
        assert r["kind"] == "federation-entity-match"
        assert r["source"] == "federation"
        assert r["method"] == "entity"
        assert len(r["sha256"]) == 64


def test_editing_a_sealed_entity_match_receipt_breaks_the_seal():
    d = entity_match_digest([_match()])
    edited = dataclasses.replace(
        d, receipts=({**d.receipts[0], "sha256": "c" * 64},))
    assert verify_digest(edited) is False


def test_two_matches_differing_only_in_confidence_seal_differently():
    a = entity_match_digest([_match(confidence=0.9)]).seal
    b = entity_match_digest([_match(confidence=0.5)]).seal
    assert a != b


def test_the_policy_and_entity_errors_are_registry_errors():
    assert issubclass(PolicyRuleError, RegistryError)
    assert issubclass(EntityResolutionError, RegistryError)


def test_policy_rules_normalizes_a_list_or_a_rules_object_and_rejects_else():
    from gather.federation_receipt import policy_rules

    rules = [_rule()]
    assert policy_rules(rules) == rules
    assert policy_rules({"rules": rules}) == rules
    with pytest.raises(PolicyRuleError, match="rules"):
        policy_rules({"policies": rules})


def test_entity_candidates_normalizes_a_list_or_a_candidates_object_and_rejects_else():
    from gather.federation_receipt import entity_candidates

    cands = [_match()]
    assert entity_candidates(cands) == cands
    assert entity_candidates({"candidates": cands}) == cands
    with pytest.raises(EntityResolutionError, match="candidates"):
        entity_candidates({"matches": cands})
