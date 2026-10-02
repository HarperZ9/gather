"""The plugin's plain-language disclosure stays true to the code it describes."""
import json
import sys
from pathlib import Path

import test_client_network

endpoint = test_client_network.endpoint
ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "client-plugin"
TITLE = "## What this plugin runs and handles"


def section(name):
    text = (PLUGIN / name).read_text(encoding="utf-8")
    start = text.index(TITLE)
    end = text.find("\n## ", start + len(TITLE))
    return text[start:] if end == -1 else text[start:end]


def test_readme_and_privacy_carry_the_same_disclosure():
    assert section("README.md") == section("PRIVACY.md")


def test_disclosure_quotes_the_exact_launch_command_and_hook_state():
    server = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["gather"]
    text = section("README.md")
    assert " ".join([server["command"], *server["args"]]) in text
    for arg in server["args"]:
        if "${" in arg:
            token = arg[arg.index("${"):arg.index("}") + 1]
            assert "`" + token + "` is" in text, token
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert "hooks" not in manifest and not (PLUGIN / "hooks").exists()
    assert "This plugin has no hooks." in text


SPY = """
import io, json, os, sys
class Spy(dict):
    reads = set()
    def __getitem__(self, key):
        self.reads.add(key)
        return super().__getitem__(key)
    def get(self, key, default=None):
        self.reads.add(key)
        return super().get(key, default)
    def __contains__(self, key):
        self.reads.add(key)
        return super().__contains__(key)
os.environ = Spy(os.environ)
sys.path.insert(0, sys.argv[1])
from gather import client_mcp
out, real = io.StringIO(), sys.stdout
sys.stdout = out
code = client_mcp.main(sys.argv[2:])
sys.stdout = real
print(json.dumps({"code": code, "rows": out.getvalue().splitlines(), "reads": sorted(Spy.reads)}))
"""


def test_every_environment_read_during_a_served_session_is_disclosed(tmp_path, endpoint):
    import subprocess
    origin, hits = endpoint
    (tmp_path / "notes.md").write_text("Synthetic note: 14 records.", encoding="utf-8")
    requests = [{"id": 1, "method": "tools/list"},
                {"id": 2, "method": "tools/call", "params": {"name": "gather.docs", "arguments": {"path": "notes.md"}}},
                {"id": 3, "method": "tools/call", "params": {"name": "gather.fetch", "arguments": {"url": origin + "/x"}}}]
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", SPY, str(ROOT / "src"),
                             "--workspace", str(tmp_path), "--allow-loopback-origin", origin],
                            input="".join(json.dumps(r) + "\n" for r in requests),
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    rows = [json.loads(line) for line in report["rows"]]
    assert report["code"] == 0
    assert [row["result"].get("isError") for row in rows[1:]] == [False, False]
    assert hits == ["/x"]
    text = section("README.md")
    assert all("`" + key + "`" in text for key in report["reads"]), report["reads"]
