import json

from gather.cli import main
from gather.mcp import handle_request


def _row(**over):
    row = {"id": "alpha-archive", "system": "Alpha Archive", "family": "papers",
           "domain": "physics", "access": "open", "adapter": "web",
           "url": "https://alpha.invalid/api", "scope": "metadata", "priority": "high"}
    row.update(over)
    return row


def _registry(tmp_path, rows, wrap=True):
    path = tmp_path / "registry.json"
    payload = {"sources": rows} if wrap else rows
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _call(name, arguments=None):
    return handle_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments or {}}})


# --- gather federation validate ---


def test_validate_json_emits_the_sealed_registry_payload(tmp_path, capsys):
    rows = [_row(), _row(id="beta-leads", access="source_lead_only", priority="low")]
    assert main(["federation", "validate", _registry(tmp_path, rows), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "gather.federation-registry/v1"
    assert [s["id"] for s in out["sources"]] == ["alpha-archive", "beta-leads"]
    assert len(out["digest"]["seal"]) == 64
    assert out["verified"] is True
    assert "coverage" not in out  # registry size is never presented as coverage
    assert "plans" not in out


def test_validate_accepts_a_bare_list_registry_file(tmp_path, capsys):
    assert main(["federation", "validate", _registry(tmp_path, [_row()], wrap=False), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["sources"]) == 1


def test_validate_human_output_counts_rows_but_never_claims_coverage(tmp_path, capsys):
    assert main(["federation", "validate", _registry(tmp_path, [_row()])]) == 0
    out = capsys.readouterr().out
    assert "1 source row(s)" in out
    assert "not coverage" in out


def test_validate_rejects_an_unknown_access_token(tmp_path, capsys):
    code = main(["federation", "validate", _registry(tmp_path, [_row(access="probably_open")])])
    assert code == 1
    assert "probably_open" in capsys.readouterr().err


def test_validate_rejects_duplicate_ids(tmp_path, capsys):
    code = main(["federation", "validate", _registry(tmp_path, [_row(), _row()])])
    assert code == 1
    assert "duplicate" in capsys.readouterr().err


def test_a_missing_registry_file_is_a_clean_error(tmp_path, capsys):
    assert main(["federation", "validate", str(tmp_path / "absent.json")]) == 1
    assert "not found" in capsys.readouterr().err


def test_a_malformed_registry_file_is_a_clean_error(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["federation", "validate", str(path)]) == 1
    assert "failed" in capsys.readouterr().err


# --- gather federation plan ---


def test_plan_json_emits_one_deterministic_plan_per_source(tmp_path, capsys):
    rows = [_row(), _row(id="keyed-api", access="key_required")]
    assert main(["federation", "plan", _registry(tmp_path, rows), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    plans = {p["id"]: p for p in out["plans"]}
    assert plans["alpha-archive"]["action"] == "capture"
    assert plans["keyed-api"]["live_probe"] is False
    assert any("hidden credentials" in f for f in plans["keyed-api"]["forbids"])
    assert out["verified"] is True


def test_plan_exits_nonzero_on_an_invalid_registry(tmp_path, capsys):
    assert main(["federation", "plan", _registry(tmp_path, [_row(priority="urgent")])]) == 1
    assert "priority" in capsys.readouterr().err


def test_plan_human_output_names_each_action(tmp_path, capsys):
    assert main(["federation", "plan", _registry(tmp_path, [_row(access="source_lead_only")])]) == 0
    out = capsys.readouterr().out
    assert "catalog_only" in out


# --- gather federation policy (policy-as-receipt) ---

_CAP = "a" * 64


def _rule(**over):
    rule = {"rule": "retry-on-throttle", "source_capture_ref": _CAP,
            "failure_class": "429", "superseded": False}
    rule.update(over)
    return rule


def _doc(tmp_path, obj):
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def test_policy_json_emits_the_sealed_policy_payload(tmp_path, capsys):
    rules = [_rule(), _rule(rule="escalate-on-forbidden", failure_class="403")]
    assert main(["federation", "policy", _doc(tmp_path, {"rules": rules}), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "gather.federation-policy/v1"
    verdicts = {r["rule"]: r["verdict"] for r in out["rules"]}
    assert verdicts["retry-on-throttle"] == "retryable_source_lead"
    assert verdicts["escalate-on-forbidden"] == "access_escalation"
    assert out["verified"] is True
    assert len(out["digest"]["seal"]) == 64


def test_policy_rejects_a_rule_with_no_provenance_capture(tmp_path, capsys):
    rule = _rule()
    del rule["source_capture_ref"]
    assert main(["federation", "policy", _doc(tmp_path, [rule])]) == 1
    assert "source_capture_ref" in capsys.readouterr().err


def test_policy_rejects_an_unknown_failure_class(tmp_path, capsys):
    assert main(["federation", "policy", _doc(tmp_path, [_rule(failure_class="418")])]) == 1
    assert "418" in capsys.readouterr().err


def test_policy_rejects_a_superseded_rule(tmp_path, capsys):
    assert main(["federation", "policy", _doc(tmp_path, [_rule(superseded=True)])]) == 1
    assert "superseded" in capsys.readouterr().err


def test_policy_human_output_names_each_verdict(tmp_path, capsys):
    assert main(["federation", "policy", _doc(tmp_path, [_rule()])]) == 0
    out = capsys.readouterr().out
    assert "retryable_source_lead" in out
    assert "not evidence" in out


# --- gather federation entity (entity-resolution) ---


def _cand(**over):
    cand = {"candidate_id": "ror-052gg0110", "identifier_path": "ror",
            "confidence": 0.98, "evidence_refs": [_CAP], "exact_id_join": True}
    cand.update(over)
    return cand


def test_entity_json_emits_the_sealed_resolution_payload(tmp_path, capsys):
    cands = [_cand(), _cand(candidate_id="ror-lo", confidence=0.4,
                            identifier_path="name", exact_id_join=False)]
    assert main(["federation", "entity", _doc(tmp_path, {"candidates": cands}), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "gather.federation-entity/v1"
    assert out["resolution"]["resolved"] == "ror-052gg0110"
    assert out["resolution"]["identifier_path"] == "ror"
    assert out["verified"] is True


def test_entity_rejects_a_match_with_no_named_identifier_path(tmp_path, capsys):
    cand = _cand()
    del cand["identifier_path"]
    assert main(["federation", "entity", _doc(tmp_path, [cand])]) == 1
    assert "identifier_path" in capsys.readouterr().err


def test_entity_rejects_candidates_out_of_confidence_order(tmp_path, capsys):
    cands = [_cand(candidate_id="ror-lo", confidence=0.4),
             _cand(candidate_id="ror-hi", confidence=0.9)]
    assert main(["federation", "entity", _doc(tmp_path, cands)]) == 1
    assert "confidence" in capsys.readouterr().err


def test_entity_rejects_a_fuzzy_name_promotion(tmp_path, capsys):
    cand = _cand(identifier_path="name", exact_id_join=False)
    assert main(["federation", "entity", _doc(tmp_path, [cand])]) == 1
    assert "exact-id" in capsys.readouterr().err


def test_entity_human_output_names_the_resolution(tmp_path, capsys):
    assert main(["federation", "entity", _doc(tmp_path, [_cand()])]) == 0
    out = capsys.readouterr().out
    assert "resolved ror-052gg0110 on ror" in out
    assert "identity join" in out


# --- MCP parity ---


def test_tools_list_includes_federation():
    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert "gather.federation" in names


def test_federation_tool_matches_the_cli_payload(tmp_path, capsys):
    path = _registry(tmp_path, [_row(), _row(id="beta-leads", access="source_lead_only")])
    resp = _call("gather.federation", {"action": "plan", "registry": path})
    mcp_body = json.loads(resp["result"]["content"][0]["text"])
    assert main(["federation", "plan", path, "--json"]) == 0
    cli_body = json.loads(capsys.readouterr().out)
    assert mcp_body == cli_body


def test_federation_tool_accepts_inline_rows():
    resp = _call("gather.federation", {"action": "validate", "registry": [_row()]})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert resp["result"].get("isError") is not True
    assert body["sources"][0]["id"] == "alpha-archive"
    assert body["verified"] is True


def test_federation_tool_accepts_an_inline_sources_object():
    resp = _call("gather.federation", {"action": "validate", "registry": {"sources": [_row()]}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["sources"][0]["id"] == "alpha-archive"


def test_federation_tool_rejects_a_bad_action():
    resp = _call("gather.federation", {"action": "guess", "registry": [_row()]})
    assert resp["result"]["isError"] is True


def test_federation_tool_rejects_an_unknown_access_token():
    resp = _call("gather.federation", {"action": "validate", "registry": [_row(access="scrape_anyway")]})
    assert resp["result"]["isError"] is True
    assert "scrape_anyway" in resp["result"]["content"][0]["text"]


# --- status parity: the surface is advertised ---


def test_status_advertises_the_federation_surface(capsys):
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "federation" in payload["native"]["commands"]
    assert "gather.federation" in payload["native"]["mcp_tools"]
