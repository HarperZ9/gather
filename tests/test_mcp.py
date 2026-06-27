import io
import json

from gather.mcp import handle_request, serve


def _call(name, arguments=None):
    return handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })


def test_initialize_announces_gather():
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["serverInfo"]["name"] == "gather"
    assert resp["result"]["protocolVersion"]


def test_tools_list_uses_catalog_names():
    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert {"gather.status", "gather.doctor", "gather.docs", "gather.arxiv", "gather.run"} <= names


def test_status_tool_returns_action_envelope():
    resp = _call("gather.status")
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["schema"] == "project-telos.flagship-action/v1"
    assert body["tool"] == "gather"
    assert body["next_actions"][0]["tool"] == "index"


def test_docs_tool_returns_receipt(tmp_path):
    source = tmp_path / "note.md"
    source.write_text("Project Telos receipt source\n", encoding="utf-8")
    resp = _call("gather.docs", {"path": str(source)})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["schema"] == "gather.catalog-digest/v1"
    assert body["verified"] is True
    assert body["dropped"] == 0
    assert body["digest"]["receipts"][0]["title"] == "note.md"


def test_run_tool_returns_cli_shaped_witnessed_record(tmp_path, capsys):
    from gather.cli import main

    source = tmp_path / "note.md"
    source.write_text("about tiling and monotiles\n", encoding="utf-8")
    config = tmp_path / "run.json"
    config.write_text(json.dumps({
        "jobs": [{"source": "docs", "target": str(source)}],
        "scope": ["tiling"],
    }), encoding="utf-8")

    resp = _call("gather.run", {"config": str(config)})
    mcp_body = json.loads(resp["result"]["content"][0]["text"])

    assert main(["run", str(config), "--json"]) == 0
    cli_body = json.loads(capsys.readouterr().out)

    for key in ("targets", "scope", "gathered", "kept", "dropped", "synthesized", "digested", "stored"):
        assert mcp_body[key] == cli_body[key]
    assert len(mcp_body["digest_seal"]) == 64
    assert len(mcp_body["seal"]) == 64


def test_unknown_tool_is_jsonrpc_error():
    resp = _call("gather.nope")
    assert resp["error"]["code"] == -32602


def test_notification_returns_none():
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_serve_writes_responses():
    inp = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    out = io.StringIO()
    assert serve(inp, out) == 0
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [row["id"] for row in rows] == [1, 2]
