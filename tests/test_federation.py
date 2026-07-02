import dataclasses

import pytest

from gather.digest import verify_digest
from gather.federation import (
    ACCESS_TOKENS,
    CAPTURE_STATUSES,
    GATHER_VERIFIED,
    GATHER_VERIFIED_WITH_WARNINGS,
    SOURCE_LEAD_ONLY,
    ForbiddenClaim,
    RegistryError,
    UnknownAccessToken,
    UnknownCaptureStatus,
    join,
    registry_digest,
    registry_rows,
    validate_registry,
    validate_row,
)
from gather.federation_policy import compile_plan, guard_claim


def _row(**over):
    row = {"id": "alpha-archive", "system": "Alpha Archive", "family": "papers",
           "domain": "physics", "access": "open", "adapter": "web",
           "url": "https://alpha.invalid/api", "scope": "metadata", "priority": "high"}
    row.update(over)
    return row


# --- the registry row contract (a closed shape with closed vocabularies) ---


def test_a_valid_row_normalizes_to_exactly_the_contract_fields():
    out = validate_row(_row())
    assert set(out) == {"id", "system", "family", "domain", "access", "adapter", "url", "scope", "priority"}
    assert out["id"] == "alpha-archive"
    assert out["access"] == "open"


def test_every_access_token_in_the_closed_vocabulary_validates():
    assert set(ACCESS_TOKENS) == {
        "open", "key_required", "rate_limited", "restricted_or_registered",
        "endpoint_alias_needed", "source_lead_only", "account_required"}
    for token in ACCESS_TOKENS:
        assert validate_row(_row(access=token))["access"] == token


def test_a_missing_field_is_rejected_by_name():
    row = _row()
    del row["adapter"]
    with pytest.raises(RegistryError, match="adapter"):
        validate_row(row)


def test_an_unknown_extra_field_is_rejected():
    with pytest.raises(RegistryError, match="coverage"):
        validate_row({**_row(), "coverage": "everything"})


def test_an_unknown_access_token_is_a_typed_rejection():
    with pytest.raises(UnknownAccessToken, match="probably_fine"):
        validate_row(_row(access="probably_fine"))
    assert issubclass(UnknownAccessToken, RegistryError)


def test_a_bad_priority_is_rejected():
    with pytest.raises(RegistryError, match="priority"):
        validate_row(_row(priority="urgent"))


def test_a_non_slug_id_is_rejected():
    for bad in ("Alpha Archive", "UPPER", "", "-lead", "a_b"):
        with pytest.raises(RegistryError, match="id"):
            validate_row(_row(id=bad))


def test_duplicate_ids_are_rejected():
    with pytest.raises(RegistryError, match="duplicate"):
        validate_registry([_row(), _row(system="Alpha Mirror")])


def test_registry_rows_accepts_a_list_or_a_sources_object_and_rejects_else():
    rows = [_row()]
    assert registry_rows(rows) == rows
    assert registry_rows({"sources": rows}) == rows
    with pytest.raises(RegistryError, match="sources"):
        registry_rows({"rows": rows})
    with pytest.raises(RegistryError, match="sources"):
        registry_rows("alpha-archive")


# --- registry receipts fold under the corpus seal machinery ---


def test_registry_digest_seals_every_row_and_verifies():
    d = registry_digest([_row(), _row(id="beta-index", system="Beta Index")])
    assert len(d.receipts) == 2
    assert verify_digest(d) is True
    for r in d.receipts:
        assert r["kind"] == "federation-source"
        assert r["source"] == "federation"
        assert r["method"] == "registry"
        assert len(r["sha256"]) == 64


def test_editing_a_sealed_registry_receipt_breaks_the_seal():
    d = registry_digest([_row()])
    edited = dataclasses.replace(d, receipts=({**d.receipts[0], "ref": "https://other.invalid/"},))
    assert verify_digest(edited) is False


def test_the_registry_seal_is_deterministic_and_order_independent():
    a, b = _row(), _row(id="beta-index", system="Beta Index")
    assert registry_digest([a, b]).seal == registry_digest([b, a]).seal
    assert registry_digest([a, b]).seal == registry_digest([a, b]).seal


def test_two_rows_differing_only_in_access_seal_differently():
    assert registry_digest([_row()]).seal != registry_digest([_row(access="key_required")]).seal


# --- the adapter policy compiler (pure, deterministic, closed over the vocabulary) ---


def test_open_compiles_to_immediate_capture_with_body_hash():
    plan = compile_plan("open")
    assert plan["access"] == "open"
    assert plan["action"] == "capture"
    assert plan["live_probe"] is True
    assert any("body hash" in step for step in plan["steps"])


def test_key_required_records_the_lead_and_never_attempts_hidden_credentials():
    plan = compile_plan("key_required")
    assert plan["live_probe"] is False
    assert any("source lead" in step for step in plan["steps"])
    assert any("hidden credentials" in f for f in plan["forbids"])
    assert any("claim availability" in f for f in plan["forbids"])


def test_rate_limited_records_the_retry_policy_before_any_live_probe():
    plan = compile_plan("rate_limited")
    assert "retry policy" in plan["steps"][0]
    assert any("before the retry policy is recorded" in f for f in plan["forbids"])


def test_restricted_or_registered_captures_docs_and_gates_on_admission():
    plan = compile_plan("restricted_or_registered")
    assert plan["live_probe"] is False
    assert any("public docs" in step for step in plan["steps"])
    assert any("admission-gated" in step for step in plan["steps"])


def test_endpoint_alias_needed_records_the_alternate_before_absence():
    plan = compile_plan("endpoint_alias_needed")
    assert any("stale endpoint" in step for step in plan["steps"])
    assert any("alternate endpoint" in step for step in plan["steps"])
    assert any("absence" in f for f in plan["forbids"])


def test_source_lead_only_catalogs_without_availability_or_coverage():
    plan = compile_plan("source_lead_only")
    assert plan["action"] == "catalog_only"
    assert plan["live_probe"] is False
    assert any("claim availability" in f for f in plan["forbids"])
    assert any("claim coverage" in f for f in plan["forbids"])


def test_account_required_gates_on_an_operator_owned_account():
    plan = compile_plan("account_required")
    assert plan["live_probe"] is False
    assert any("account" in f for f in plan["forbids"])
    assert any("hidden credentials" in f for f in plan["forbids"])


def test_an_unknown_access_token_is_a_typed_rejection_from_the_compiler():
    with pytest.raises(UnknownAccessToken, match="scrape_anyway"):
        compile_plan("scrape_anyway")


def test_the_compiler_is_deterministic_and_returns_fresh_plans():
    first = compile_plan("open")
    first["steps"].append("tampered")
    assert "tampered" not in compile_plan("open")["steps"]
    assert compile_plan("open") == compile_plan("open")
    for token in ACCESS_TOKENS:
        assert compile_plan(token)["access"] == token


# --- evidence-status derivation: join() over a source's capture statuses ---


def test_the_capture_status_vocabulary_is_closed_and_pinned():
    assert set(CAPTURE_STATUSES) == {
        "GATHER_VERIFIED", "GATHER_EMPTY_WARNING", "GATHER_DROPPED_WARNING",
        "HTTP_503_WARNING", "HTTP_400_QUERY_SHAPE_WARNING", "HTTP_429_RATE_LIMIT_WARNING"}


def test_only_verified_captures_join_to_verified():
    assert join(["GATHER_VERIFIED"]) == GATHER_VERIFIED
    assert join(["GATHER_VERIFIED", "GATHER_VERIFIED"]) == GATHER_VERIFIED


def test_verified_plus_any_warning_joins_to_verified_with_warnings():
    assert join(["GATHER_VERIFIED", "HTTP_503_WARNING"]) == GATHER_VERIFIED_WITH_WARNINGS
    assert join(["GATHER_EMPTY_WARNING", "GATHER_VERIFIED"]) == GATHER_VERIFIED_WITH_WARNINGS


def test_warnings_only_join_to_the_worst_sorted_first():
    assert join(["HTTP_503_WARNING", "GATHER_EMPTY_WARNING"]) == "GATHER_EMPTY_WARNING"
    assert join(["HTTP_429_RATE_LIMIT_WARNING", "HTTP_400_QUERY_SHAPE_WARNING"]) == "HTTP_400_QUERY_SHAPE_WARNING"
    assert join(["HTTP_503_WARNING"]) == "HTTP_503_WARNING"


def test_no_captures_join_to_source_lead_only():
    assert join([]) == SOURCE_LEAD_ONLY


def test_join_is_order_independent():
    statuses = ["HTTP_503_WARNING", "GATHER_VERIFIED", "GATHER_DROPPED_WARNING"]
    assert join(statuses) == join(list(reversed(statuses)))


def test_an_unknown_capture_status_is_a_typed_rejection():
    with pytest.raises(UnknownCaptureStatus, match="GATHER_PROBABLY_FINE"):
        join(["GATHER_VERIFIED", "GATHER_PROBABLY_FINE"])
    assert issubclass(UnknownCaptureStatus, RegistryError)


# --- negative fixtures: known-bad claims that MUST reject ---
# A verifier that cannot fail on a known-bad input is not a verifier. Each fixture below is
# a claim pattern the federation contract exists to refuse; every one must raise, typed.


def test_source_count_as_world_coverage_is_rejected():
    with pytest.raises(ForbiddenClaim, match="source_count_as_world_coverage"):
        guard_claim("coverage", "registry_size")


def test_registry_listing_as_endpoint_availability_is_rejected():
    with pytest.raises(ForbiddenClaim, match="registry_listing_as_endpoint_availability"):
        guard_claim("availability", "registry_listing")
    # mechanically: a listed source with zero captures is a lead, never an availability claim
    assert join([]) == SOURCE_LEAD_ONLY
    assert join([]) != GATHER_VERIFIED


def test_metadata_as_full_text_is_rejected():
    with pytest.raises(ForbiddenClaim, match="metadata_as_full_text"):
        guard_claim("full_text", "metadata")


def test_closed_key_source_as_available_is_rejected():
    with pytest.raises(ForbiddenClaim, match="closed_key_source_as_available"):
        guard_claim("availability", "access_token")
    # mechanically: the key_required plan itself forbids the claim
    assert any("claim availability" in f for f in compile_plan("key_required")["forbids"])


def test_empty_capture_as_match_is_rejected():
    with pytest.raises(ForbiddenClaim, match="empty_capture_as_match"):
        guard_claim("match", "empty_capture")
    # mechanically: an empty capture joins to its warning, never to verified
    assert join(["GATHER_EMPTY_WARNING"]) == "GATHER_EMPTY_WARNING"
    assert join(["GATHER_EMPTY_WARNING"]) != GATHER_VERIFIED


def test_route_failure_as_source_absence_is_rejected():
    with pytest.raises(ForbiddenClaim, match="route_failure_as_source_absence"):
        guard_claim("absence", "route_failure")
    # mechanically: a 503 joins to a warning about the route, never a verdict about the source
    assert join(["HTTP_503_WARNING"]) == "HTTP_503_WARNING"


def test_the_guard_default_denies_any_pair_outside_the_allowed_table():
    for claim, basis in (("coverage", "verified_capture"), ("availability", "metadata"),
                         ("world_peace", "verified_capture"), ("match", "registry_size")):
        with pytest.raises(ForbiddenClaim):
            guard_claim(claim, basis)


def test_verified_capture_grounds_the_allowed_claims():
    for claim in ("availability", "match", "full_text"):
        assert guard_claim(claim, "verified_capture") == {
            "claim": claim, "basis": "verified_capture", "allowed": True}
    assert guard_claim("absence", "exhausted_alternates")["allowed"] is True
