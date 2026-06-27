import json

from gather.cli import main


def test_status_json_is_action_envelope(capsys):
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "project-telos.flagship-action/v1"
    assert payload["tool"] == "gather"
    assert payload["status"] == "MATCH"
    assert "gather.run" in payload["native"]["mcp_tools"]
    assert payload["next_actions"][0]["tool"] == "index"


def test_doctor_human_prints_verdict_and_next_action(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("status=MATCH tool=gather command=doctor")
    assert "next: crucible assess" in out


def test_demo_json_names_docs_command(capsys):
    assert main(["demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["native"]["command"] == "gather docs <path> --json"
