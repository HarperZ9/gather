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
