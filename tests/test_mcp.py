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
    run_schema = next(tool["inputSchema"] for tool in resp["result"]["tools"] if tool["name"] == "gather.run")
    assert "oneOf" in run_schema["properties"]["config"]


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


def test_run_tool_accepts_inline_config_for_host_neutral_mcp(tmp_path):
    source = tmp_path / "note.md"
    source.write_text("about receptors and measured constants\n", encoding="utf-8")

    resp = _call("gather.run", {
        "config": {
            "jobs": [{"source": "docs", "target": str(source)}],
            "scope": ["constants"],
        }
    })
    body = json.loads(resp["result"]["content"][0]["text"])

    assert resp["result"].get("isError") is not True
    assert body["targets"] == [["docs", str(source)]]
    assert body["scope"] == ["constants"]
    assert body["gathered"] == 1
    assert body["kept"] == 1
    assert len(body["digest_seal"]) == 64


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


# --- gather.pilot MCP parity -------------------------------------------------

import socket  # noqa: E402
from pathlib import Path  # noqa: E402

_PILOT_MANIFEST = {
    "schema": "gather.pilot-manifest/1",
    "pilot_id": "mcp-parity",
    "title": "MCP parity pilot",
    "mode": "offline",
    "deployment": {"mode": "workstation", "custodian": "customer"},
    "policy": {
        "allowed_hosts": ["example.org"],
        "trusted_browser_hosts": [],
        "allowed_local_roots": ["fixtures"],
        "enabled_adapters": ["web"],
        "credentials": [],
        "report_private_content": False,
    },
    "missions": [
        {
            "id": "venture",
            "title": "Venture",
            "sources": [
                {
                    "id": "portfolio",
                    "adapter": "web",
                    "target": "https://example.org/portfolio",
                    "fixture": "fixtures/portfolio.html",
                    "refresh_fixture": None,
                    "visibility": "public",
                    "monitor": False,
                    "required": True,
                    "extraction": None,
                    "options": {},
                }
            ],
        }
    ],
}


def _pilot_fixtures(tmp_path: Path) -> Path:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "portfolio.html").write_text(
        "<!doctype html><html><body><h1>Portfolio</h1><p>seed</p></body></html>",
        encoding="utf-8",
    )
    return tmp_path


def _no_network(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))


def test_pilot_tool_advertised():
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert "gather.pilot" in names
    schema = next(t["inputSchema"] for t in resp["result"]["tools"] if t["name"] == "gather.pilot")
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["action", "output"]


def test_pilot_run_inline_manifest(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _pilot_fixtures(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "pilot"
    resp = _call("gather.pilot", {
        "action": "run",
        "manifest": _PILOT_MANIFEST,
        "output": str(out),
    })
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["action"] == "run"
    assert body["manifest_digest"]
    assert (out / "report.json").exists()


def test_pilot_verify_returns_checks(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _pilot_fixtures(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "pilot"
    _call("gather.pilot", {"action": "run", "manifest": _PILOT_MANIFEST, "output": str(out)})
    resp = _call("gather.pilot", {"action": "verify", "output": str(out)})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["action"] == "verify"
    assert body["ok"] is True


def test_pilot_run_rejects_unknown_action():
    resp = _call("gather.pilot", {"action": "bogus", "output": "x"})
    assert resp["result"]["isError"] is True
    assert "error" in resp["result"]["content"][0]["text"]


def test_pilot_run_missing_output():
    resp = _call("gather.pilot", {"action": "run", "manifest": _PILOT_MANIFEST})
    assert resp["result"]["isError"] is True


def test_pilot_bundle_shared(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _pilot_fixtures(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "pilot"
    _call("gather.pilot", {"action": "run", "manifest": _PILOT_MANIFEST, "output": str(out)})
    bundle = tmp_path / "shared.zip"
    resp = _call("gather.pilot", {
        "action": "bundle",
        "output": str(out),
        "bundle_output": str(bundle),
        "visibility": "shared",
    })
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["action"] == "bundle"
    assert body["visibility"] == "shared"
    assert bundle.exists()

