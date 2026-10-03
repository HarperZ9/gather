"""Launch-only grants: a gather.run config or pilot manifest from tool arguments cannot run a
command, reach the network or send a credential unless the server was launched with a grant
naming it. Arguments can narrow a grant and never widen it."""
import io
import json
import socket
import subprocess
import sys

import pytest

from gather.grants import Grants
from gather.mcp import handle_request, serve

FAKE_SECRET = "planted-fake-secret-value-7c1e"
NETWORK_SOURCES = ("web", "feed", "arxiv", "video", "api", "browser", "reddit")


def _req(name, arguments, mid=3):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def _call(name, arguments, **kw):
    return handle_request(_req(name, arguments), **kw)


def _refusal(resp):
    result = resp["result"]
    assert result.get("isError") is True, result
    return result["structuredContent"]


@pytest.fixture
def sealed(monkeypatch):
    """Record and refuse every socket or child process a call tries to open."""
    attempts = []

    def refuse(kind):
        def _refuse(*args, **kwargs):
            attempts.append(kind)
            raise OSError(f"sealed test: {kind} refused")
        return _refuse

    monkeypatch.setattr(socket, "getaddrinfo", refuse("dns"))
    monkeypatch.setattr(socket, "create_connection", refuse("connect"))
    monkeypatch.setattr(subprocess, "run", refuse("subprocess"))
    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess"))
    return attempts


def _doc(tmp_path):
    source = tmp_path / "note.md"
    source.write_text("about tiling\n", encoding="utf-8")
    return str(source)


def _marker_command(marker):
    code = f"import sys; open({str(marker)!r}, 'w').write('x'); sys.stdout.write('a statement')"
    return [sys.executable, "-c", code]


# --- launch parsing ---------------------------------------------------------------------------

def test_grants_parse_from_launch_environment():
    grants = Grants.from_env({
        "GATHER_ALLOW_EXEC": " llm , /opt/prov/check ",
        "GATHER_ALLOW_NETWORK": "web,feed",
        "GATHER_AUTH_ENV_ALLOW": "GATHER_API_TOKEN@API.Example.com, OTHER_TOKEN@data.example.org",
    })
    assert grants.exec_commands == frozenset({"llm", "/opt/prov/check"})
    assert grants.network_sources == frozenset({"web", "feed"})
    assert grants.auth_env == frozenset({("GATHER_API_TOKEN", "api.example.com"),
                                         ("OTHER_TOKEN", "data.example.org")})


def test_nothing_is_granted_by_default():
    grants = Grants.from_env({})
    assert not grants.exec_commands and not grants.network_sources and not grants.auth_env


def test_network_all_names_every_network_source():
    assert Grants.from_env({"GATHER_ALLOW_NETWORK": "all"}).network_sources >= set(NETWORK_SOURCES)


def test_an_auth_env_entry_without_a_host_is_ignored(capsys):
    grants = Grants.from_env({"GATHER_AUTH_ENV_ALLOW": "GATHER_API_TOKEN,lower@x.example"})
    assert grants.auth_env == frozenset()
    err = capsys.readouterr().err
    assert "GATHER_AUTH_ENV_ALLOW" in err and "ignored" in err


# --- exec: synthesizer and provenance ---------------------------------------------------------

@pytest.mark.parametrize("key", ["synthesizer", "provenance"])
def test_a_config_command_without_the_exec_grant_returns_grant_required(tmp_path, key):
    marker = tmp_path / "RAN"
    resp = _call("gather.run", {"config": {
        "jobs": [{"source": "docs", "target": _doc(tmp_path)}], key: _marker_command(marker)}})
    body = _refusal(resp)
    assert body["code"] == "GRANT_REQUIRED" and body["setup"] == "GATHER_ALLOW_EXEC"
    assert body["retryable"] is False
    assert not marker.exists(), "the configured command ran without a launch grant"


def test_a_config_file_on_disk_is_no_more_trusted_than_an_inline_config(tmp_path):
    marker = tmp_path / "RAN"
    config = tmp_path / "planted-run.json"
    config.write_text(json.dumps({"jobs": [{"source": "docs", "target": _doc(tmp_path)}],
                                  "synthesizer": _marker_command(marker)}), encoding="utf-8")
    assert _refusal(_call("gather.run", {"config": str(config)}))["code"] == "GRANT_REQUIRED"
    assert not marker.exists()


def test_arguments_cannot_grant_themselves_exec(tmp_path):
    marker = tmp_path / "RAN"
    cmd = _marker_command(marker)
    resp = _call("gather.run", {
        "allow_exec": True, "grants": {"exec": [cmd[0]]}, "GATHER_ALLOW_EXEC": cmd[0],
        "config": {"jobs": [{"source": "docs", "target": _doc(tmp_path)}], "synthesizer": cmd,
                   "allow_exec": True, "grants": {"exec": [cmd[0]]}},
    })
    assert _refusal(resp)["code"] == "GRANT_REQUIRED"
    assert not marker.exists()


def test_the_exec_grant_runs_only_the_command_it_names(tmp_path):
    marker = tmp_path / "RAN"
    cmd = _marker_command(marker)
    config = {"jobs": [{"source": "docs", "target": _doc(tmp_path)}], "synthesizer": cmd}
    other = Grants(exec_commands=frozenset({"some-other-cli"}))
    assert _refusal(_call("gather.run", {"config": config}, grants=other))["code"] == "GRANT_REQUIRED"
    assert not marker.exists()
    resp = _call("gather.run", {"config": config}, grants=Grants(exec_commands=frozenset({cmd[0]})))
    assert resp["result"].get("isError") is not True, resp
    assert marker.exists()
    assert json.loads(resp["result"]["content"][0]["text"])["synthesized"] is True


# --- network sources ----------------------------------------------------------------------------

@pytest.mark.parametrize("source", NETWORK_SOURCES)
def test_a_network_source_without_the_network_grant_returns_grant_required(source, sealed):
    target = "https://example.org/x"
    resp = _call("gather.run", {"config": {"jobs": [{"source": source, "target": target}]}})
    body = _refusal(resp)
    assert body["code"] == "GRANT_REQUIRED" and body["setup"] == "GATHER_ALLOW_NETWORK"
    assert sealed == [], f"{source} reached the network or a child before the grant check"


def test_a_network_grant_for_one_source_does_not_cover_another(sealed):
    grants = Grants(network_sources=frozenset({"web"}))
    resp = _call("gather.run", {"config": {"jobs": [{"source": "feed", "target": "https://example.org/f"}]}},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_ALLOW_NETWORK"
    assert sealed == []


def test_local_docs_runs_need_no_grant(tmp_path):
    resp = _call("gather.run", {"config": {"jobs": [{"source": "docs", "target": _doc(tmp_path)}]}})
    assert resp["result"].get("isError") is not True
    assert json.loads(resp["result"]["content"][0]["text"])["gathered"] == 1


# --- credentials --------------------------------------------------------------------------------

@pytest.fixture
def api_stub(monkeypatch):
    """Stub the HTTP edge of the api adapter and record every header it would send."""
    import gather.api as api_mod

    sent = []

    def fake_http_get(url, *, timeout, headers=None, **_kw):
        sent.append({"url": url, "headers": dict(headers or {})})
        return b'[{"id": "r1", "title": "row"}]', "application/json"

    monkeypatch.setattr(api_mod, "http_get", fake_http_get)
    monkeypatch.setenv("PLANTED_FAKE_SECRET", FAKE_SECRET)
    monkeypatch.setenv("GATHER_API_TOKEN", FAKE_SECRET + "-allowed")
    return sent


def _api_config(auth_env, url="https://api.example.com/items"):
    return {"jobs": [{"source": "api", "target": url, "auth_env": auth_env}]}


def test_an_auth_env_off_the_allowlist_is_refused_and_never_sent(api_stub):
    grants = Grants(network_sources=frozenset({"api"}),
                    auth_env=frozenset({("GATHER_API_TOKEN", "api.example.com")}))
    resp = _call("gather.run", {"config": _api_config("PLANTED_FAKE_SECRET")}, grants=grants)
    body = _refusal(resp)
    assert body["code"] == "GRANT_REQUIRED" and body["setup"] == "GATHER_AUTH_ENV_ALLOW"
    assert api_stub == [], "the adapter sent a request with an off-list credential"
    assert FAKE_SECRET not in json.dumps(resp)


def test_an_auth_env_is_refused_and_never_sent_with_no_grants_at_all(api_stub):
    resp = _call("gather.run", {"config": _api_config("PLANTED_FAKE_SECRET")})
    assert _refusal(resp)["code"] == "GRANT_REQUIRED"
    assert api_stub == []
    assert FAKE_SECRET not in json.dumps(resp)


def test_an_allowlisted_credential_goes_only_to_its_bound_host(api_stub):
    grants = Grants(network_sources=frozenset({"api"}),
                    auth_env=frozenset({("GATHER_API_TOKEN", "api.example.com")}))
    resp = _call("gather.run", {"config": _api_config("GATHER_API_TOKEN", "https://evil.example/collect")},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_AUTH_ENV_ALLOW"
    assert api_stub == []


def test_an_allowlisted_credential_reaches_its_bound_host_and_never_the_output(api_stub):
    grants = Grants(network_sources=frozenset({"api"}),
                    auth_env=frozenset({("GATHER_API_TOKEN", "api.example.com")}))
    resp = _call("gather.run", {"config": _api_config("GATHER_API_TOKEN")}, grants=grants)
    assert resp["result"].get("isError") is not True, resp
    assert [s["headers"]["Authorization"] for s in api_stub] == [f"Bearer {FAKE_SECRET}-allowed"]
    assert FAKE_SECRET not in json.dumps(resp)


# --- the grant is read once, at launch ----------------------------------------------------------

def _lines_that_widen_the_env_midway(first, second, monkeypatch, value):
    yield json.dumps(first) + "\n"
    monkeypatch.setenv("GATHER_ALLOW_EXEC", value)
    yield json.dumps(second) + "\n"


def test_serve_reads_grants_once_at_launch(tmp_path, monkeypatch):
    marker = tmp_path / "RAN"
    cmd = _marker_command(marker)
    monkeypatch.delenv("GATHER_ALLOW_EXEC", raising=False)
    run = _req("gather.run", {"config": {"jobs": [{"source": "docs", "target": _doc(tmp_path)}],
                                         "synthesizer": cmd}}, mid=2)
    out = io.StringIO()
    serve(_lines_that_widen_the_env_midway({"jsonrpc": "2.0", "id": 1, "method": "ping"}, run,
                                           monkeypatch, cmd[0]), out)
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert rows[1]["result"]["structuredContent"]["code"] == "GRANT_REQUIRED"
    assert not marker.exists()


def test_serve_honours_the_exec_grant_set_at_launch(tmp_path, monkeypatch):
    marker = tmp_path / "RAN"
    cmd = _marker_command(marker)
    monkeypatch.setenv("GATHER_ALLOW_EXEC", cmd[0])
    run = _req("gather.run", {"config": {"jobs": [{"source": "docs", "target": _doc(tmp_path)}],
                                         "synthesizer": cmd}}, mid=2)
    out = io.StringIO()
    serve(io.StringIO(json.dumps(run) + "\n"), out)
    assert json.loads(out.getvalue())["result"].get("isError") is not True
    assert marker.exists()


def test_cli_flags_grant_at_launch(tmp_path, monkeypatch):
    from gather.cli import main

    marker = tmp_path / "RAN"
    cmd = _marker_command(marker)
    monkeypatch.delenv("GATHER_ALLOW_EXEC", raising=False)
    run = _req("gather.run", {"config": {"jobs": [{"source": "docs", "target": _doc(tmp_path)}],
                                         "synthesizer": cmd}}, mid=2)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(run) + "\n"))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert main(["mcp", "--allow-exec", cmd[0]]) == 0
    assert json.loads(out.getvalue())["result"].get("isError") is not True
    assert marker.exists()


def test_the_operator_cli_run_keeps_running_its_own_config(tmp_path, capsys):
    from gather.cli import main

    marker = tmp_path / "RAN"
    config = tmp_path / "run.json"
    config.write_text(json.dumps({"jobs": [{"source": "docs", "target": _doc(tmp_path)}],
                                  "synthesizer": _marker_command(marker)}), encoding="utf-8")
    assert main(["run", str(config), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["synthesized"] is True
    assert marker.exists()


# --- pilot manifests from arguments -------------------------------------------------------------

def _live_manifest(adapter, target, options=None, credentials=()):
    return {
        "schema": "gather.pilot-manifest/1", "pilot_id": "grant-probe", "title": "Grant probe",
        "mode": "live", "deployment": {"mode": "workstation", "custodian": "customer"},
        "policy": {"allowed_hosts": ["example.org", "api.example.com"],
                   "trusted_browser_hosts": ["example.org"], "allowed_local_roots": [],
                   "enabled_adapters": [adapter], "credentials": list(credentials),
                   "report_private_content": False},
        "missions": [{"id": "m", "title": "M", "sources": [{
            "id": "s", "adapter": adapter, "target": target, "fixture": None,
            "refresh_fixture": None, "visibility": "public", "monitor": False,
            "required": True, "extraction": None, "options": options or {}}]}],
    }


def test_a_live_pilot_manifest_needs_the_network_grant(tmp_path, sealed):
    resp = _call("gather.pilot", {"action": "run", "output": str(tmp_path / "p"),
                                  "manifest": _live_manifest("web", "https://example.org/a")})
    body = _refusal(resp)
    assert body["code"] == "GRANT_REQUIRED" and body["setup"] == "GATHER_ALLOW_NETWORK"
    assert sealed == []
    assert not (tmp_path / "p").exists()


def test_a_live_pilot_manifest_cannot_send_an_off_list_credential(tmp_path, api_stub):
    manifest = _live_manifest("api", "https://api.example.com/items",
                              {"auth_env": "PLANTED_FAKE_SECRET"}, ["PLANTED_FAKE_SECRET"])
    grants = Grants(network_sources=frozenset({"api"}),
                    auth_env=frozenset({("GATHER_API_TOKEN", "api.example.com")}))
    resp = _call("gather.pilot", {"action": "run", "output": str(tmp_path / "p"), "manifest": manifest},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_AUTH_ENV_ALLOW"
    assert api_stub == []
    assert FAKE_SECRET not in json.dumps(resp)


def test_a_live_pilot_manifest_cannot_name_its_own_browser_executable(tmp_path, sealed):
    manifest = _live_manifest("browser", "https://example.org/a", {"browser": "planted-browser"})
    grants = Grants(network_sources=frozenset({"browser"}))
    resp = _call("gather.pilot", {"action": "run", "output": str(tmp_path / "p"), "manifest": manifest},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_ALLOW_EXEC"
    assert sealed == []


# --- found in the security review of this change ------------------------------------------------

def test_a_live_pilot_manifest_cannot_turn_off_the_browser_sandbox(tmp_path, sealed):
    manifest = _live_manifest("browser", "https://example.org/a", {"no_sandbox": True})
    grants = Grants(network_sources=frozenset({"browser"}))
    resp = _call("gather.pilot", {"action": "run", "output": str(tmp_path / "p"), "manifest": manifest},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_ALLOW_EXEC"
    assert sealed == []


def test_a_credential_is_never_sent_over_plain_http(api_stub):
    grants = Grants(network_sources=frozenset({"api"}),
                    auth_env=frozenset({("GATHER_API_TOKEN", "api.example.com")}))
    resp = _call("gather.run", {"config": _api_config("GATHER_API_TOKEN", "http://api.example.com/items")},
                 grants=grants)
    assert _refusal(resp)["setup"] == "GATHER_AUTH_ENV_ALLOW"
    assert api_stub == []


def test_refresh_checks_the_manifest_it_actually_captures_from(tmp_path, monkeypatch, sealed):
    """The grant check and the capture must use one read of the stored manifest; a second read
    could see a file swapped after the check."""
    import gather.pilot as pilot_mod
    from gather.pilot_manifest import load_pilot_manifest

    seen = []

    def counting_load(path):
        seen.append(str(path))
        return load_pilot_manifest(path)

    monkeypatch.setattr("gather.pilot_manifest.load_pilot_manifest", counting_load)
    monkeypatch.setattr(pilot_mod, "verify_pilot", lambda root: type("V", (), {"ok": True})())
    out = tmp_path / "p"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps(_live_manifest("web", "https://example.org/a")),
                                       encoding="utf-8")
    denied = _call("gather.pilot", {"action": "refresh", "output": str(out)})
    assert _refusal(denied)["setup"] == "GATHER_ALLOW_NETWORK"
    seen.clear()
    _call("gather.pilot", {"action": "refresh", "output": str(out)},
          grants=Grants(network_sources=frozenset({"web"})))
    assert len(seen) == 1, f"the stored manifest was read {len(seen)} times in one refresh"


def test_the_run_and_pilot_descriptions_state_the_grant():
    tools = {t["name"]: t for t in handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
             ["result"]["tools"]}
    assert "GRANT_REQUIRED" in tools["gather.run"]["description"]
    assert "launch grant" in tools["gather.pilot"]["description"]
