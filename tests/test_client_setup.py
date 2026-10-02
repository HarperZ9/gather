"""Execute the manifest-expanded launch arguments using only local fixtures."""
import json
import sys
from pathlib import Path

import pytest
import test_client_network
from test_client_network import call, launch

endpoint = test_client_network.endpoint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def config_args(workspace, **settings):
    import build_client_package as package
    manifest = package.native_manifest(package.SPEC, package.version(), "gather-local.exe")
    values = {key: value.get("default", "") for key, value in manifest["user_config"].items()}
    values.update(workspace=str(workspace), **settings)
    args = manifest["server"]["mcp_config"]["args"]
    for key, value in values.items():
        args = [arg.replace("${user_config." + key + "}", value) for arg in args]
    # The source test launcher supplies this same workspace separately.
    assert args[:2] == ["--workspace", str(workspace)]
    return args[2:]


@pytest.mark.parametrize("settings", [{}, {"allowed_origins": "", "loopback_origins": ""}])
def test_manifest_defaults_start_without_network(tmp_path, endpoint, settings):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin)], config_args(tmp_path, **settings))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["isError"]
    assert hits == []


def test_manifest_enabled_origin_fetches_real_fixture(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin+"/source")],
                    config_args(tmp_path, loopback_origins=json.dumps([origin])))
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)["result"]
    assert not response["isError"], response
    assert json.loads(response["content"][0]["text"])["text"] == "Synthetic evidence: 14 records."
    assert hits == ["/source"]


@pytest.mark.parametrize("value", ["not-json", "{}", "null", '"https://example.com"', "[1]", "[true]", "[null]", '["http://127.0.0.1:1"]'])
def test_manifest_malformed_public_setting_refuses_launch(tmp_path, value):
    result = launch(tmp_path, [{"id": 1, "method": "initialize"}],
                    config_args(tmp_path, allowed_origins=value))
    assert result.returncode == 2
    assert result.stdout == ""


def test_manifest_argument_strings_do_not_become_flags(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin)], config_args(tmp_path,
        loopback_origins=json.dumps([origin + " --allow-origin https://example.com"])))
    assert result.returncode == 2
    assert hits == []


def test_claude_plugin_arguments_start_the_server_with_default_settings(tmp_path):
    import subprocess
    config = json.loads((ROOT / "client-plugin/.mcp.json").read_text(encoding="utf-8"))["mcpServers"]["gather"]
    values = {"CLAUDE_PLUGIN_ROOT": str(ROOT / "client-plugin"), "user_config.workspace": str(tmp_path),
              "user_config.allowed_origins": "[]", "user_config.loopback_origins": "[]"}
    args = config["args"]
    for key, value in values.items():
        args = [arg.replace("${" + key + "}", value) for arg in args]
    assert not any("${" in arg for arg in args)
    requests = [{"id": 1, "method": "initialize"}, {"id": 2, "method": "tools/list"}]
    result = subprocess.run([sys.executable, *args], input="".join(json.dumps(r) + "\n" for r in requests),
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [tool["name"] for tool in rows[1]["result"]["tools"]] == ["gather.docs"]
