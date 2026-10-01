"""Meaningful client boundary regressions; no model or network calls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gather import __version__
from gather.client_mcp import confined, handle


def request(name, args):
    return {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": name, "arguments": args}}

def test_version_parity(tmp_path):
    result = handle({"id": 1, "method": "initialize"}, tmp_path)
    assert result["result"]["serverInfo"]["version"] == __version__

@pytest.mark.parametrize("value", ["../outside.txt", "//localhost/share", "C:/Windows/system.ini", "sample.md:secret", "NUL"])
def test_outside_or_device_path_is_rejected(tmp_path, value):
    with pytest.raises((ValueError, OSError)):
        confined(tmp_path, value)

def test_links_refused(tmp_path):
    outside = tmp_path.parent / "outside-client.txt"
    outside.write_text("private", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError):
        confined(tmp_path, str(link))

def test_ungranted_tool_refused_even_with_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GATHER_ALLOW_EXEC", "all")
    monkeypatch.setenv("GATHER_ALLOW_NETWORK", "all")
    result = handle(request("gather.run", {"allow_exec": True}), tmp_path)
    assert result["result"]["isError"] is True
    assert "TOOL_NOT_GRANTED" in result["result"]["content"][0]["text"]

def test_arguments_cannot_grant_permissions(tmp_path):
    result = handle(request("gather.docs", {"path":"sample.md","allow_exec":True}), tmp_path)
    assert result["result"]["isError"] is True

def test_missing_launch_root_exits_without_server(tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-I", "-S", "-B", str(root / "client-plugin/server/serve.py")]
    result = subprocess.run(command, cwd=tmp_path, input="", capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2
    assert "--workspace" in result.stderr

def test_actual_stdio_safe_workflow(tmp_path):
    (tmp_path / "sample.md").write_text("A synthetic source contains 14 records.", encoding="utf-8")
    (tmp_path / "thesis.json").write_text(json.dumps({"title": "Synthetic",
        "claims": [{"statement": "14 records exist", "falsification": "a count other than 14"}]}), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    requests = [{"id": 1, "method": "initialize"}, request("gather.docs", {"path":"sample.md"})]
    command = [sys.executable, "-I", "-S", "-B", str(root / "client-plugin/server/serve.py"),
               "--workspace", str(tmp_path)]
    result = subprocess.run(command, cwd=tmp_path, input="".join(json.dumps(r)+"\n" for r in requests),
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    assert rows[0]["result"]["serverInfo"]["version"] == __version__
    assert rows[1]["result"]["isError"] is False, rows[1]
    assert json.loads(rows[1]["result"]["content"][0]["text"])
