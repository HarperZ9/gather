"""The plugin folder carries its own server code and runs with nothing else beside it."""
import ast
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import test_client_network

endpoint = test_client_network.endpoint
ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "client-plugin"
sys.path.insert(0, str(ROOT / "scripts"))
package = __import__("build_client_package")

MISSING = "gather: the server code is missing from the plugin folder. Reinstall the plugin."


def test_vendored_server_code_matches_src():
    drift = package.vendored_drift()
    assert drift == {"missing": [], "extra": [], "changed": []}, (
        f"client-plugin/server/src/ drifted from src/: {drift}. Run: {package.SYNC_COMMAND}")


def test_plugin_folder_fits_directory_limits():
    files = [path for path in PLUGIN.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    assert len(files) <= 512
    # The 256 KiB rule covers files other than images and fonts; the icon has its own 2 MB cap.
    media = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf"}
    other = [path for path in files if path.suffix.lower() not in media]
    assert all(path.stat().st_size < 256 * 1024 for path in other), max(other, key=lambda p: p.stat().st_size)
    assert all(path.stat().st_size < 2 * 1024 * 1024 for path in files if path not in other)
    assert not [path for path in files if path.name == ".gitattributes"]


def test_source_zip_takes_server_code_once_from_src(tmp_path):
    archive = package.build(tmp_path / "build", "dev")[0]
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    server = [name for name in names if name.startswith(package.VENDORED)]
    assert len(names) == len(set(names))
    assert sorted(server) == sorted(package.vendored_expected())
    assert not [name for name in names if "server/src/server/" in name]


def launch(root, workspace, requests=None, **settings):
    config = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["gather"]
    claude = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    values = {"CLAUDE_PLUGIN_ROOT": str(root), "user_config.workspace": str(workspace)}
    values.update({"user_config." + key: setting.get("default", "")
                   for key, setting in claude["userConfig"].items() if key != "workspace"})
    values.update({"user_config." + key: value for key, value in settings.items()})

    def expand(text):
        for key, value in values.items():
            text = text.replace("${" + key + "}", value)
        assert "${" not in text, text
        return text

    command = sys.executable if config["command"] == "python3" else expand(config["command"])
    env = {"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           **{key: expand(value) for key, value in config.get("env", {}).items()}}
    requests = requests or [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    return subprocess.run([command, *[expand(arg) for arg in config["args"]]], cwd=workspace, env=env,
                          input="".join(json.dumps(r) + "\n" for r in requests),
                          capture_output=True, text=True, timeout=20, check=False)


def test_copied_plugin_folder_alone_starts_and_lists_tools(tmp_path):
    root = tmp_path / "installed" / "gather-local"
    shutil.copytree(PLUGIN, root, ignore=shutil.ignore_patterns("__pycache__"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = launch(root, workspace)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[0]["result"]["serverInfo"]["name"] == "gather-local"
    assert [tool["name"] for tool in rows[1]["result"]["tools"]] == ["gather.docs"]

    shutil.rmtree(root / "server" / "src")
    result = launch(root, workspace)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == MISSING


CREDENTIAL_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(TOKEN|API_KEY|SECRET|PASSWORD|CREDENTIALS?)$")


def test_vendored_code_names_no_credential_variable():
    """The vendored closure leaves out the full server's credential paths, such as GATHER_API_TOKEN."""
    folder = PLUGIN / "server" / "src"
    named = []
    for path in folder.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "GATHER_API_TOKEN" not in text, path
        named += [(path.name, node.value) for node in ast.walk(ast.parse(text))
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and CREDENTIAL_NAME.match(node.value)]
    assert named == []


def test_closure_follows_function_level_and_relative_imports(tmp_path):
    from client_closure import closure
    package = tmp_path / "pkg"
    (package / "sub").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "entry.py").write_text("def run():\n    from . import lazy\n", encoding="utf-8")
    (package / "lazy.py").write_text("from .sub import leaf\n", encoding="utf-8")
    (package / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (package / "sub" / "leaf.py").write_text("", encoding="utf-8")
    (package / "sub" / "table.json").write_text("{}", encoding="utf-8")
    (package / "unused.py").write_text("", encoding="utf-8")
    assert closure(tmp_path, b"from pkg.entry import run\n", "pkg") == [
        "pkg/__init__.py", "pkg/entry.py", "pkg/lazy.py", "pkg/sub/__init__.py",
        "pkg/sub/leaf.py", "pkg/sub/table.json"]


def test_copied_plugin_folder_alone_reads_a_document_and_fetches_a_granted_origin(tmp_path, endpoint):
    origin, hits = endpoint
    root = tmp_path / "installed" / "gather-local"
    shutil.copytree(PLUGIN, root, ignore=shutil.ignore_patterns("__pycache__"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.md").write_text("Synthetic note: 14 records.", encoding="utf-8")
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "gather.docs", "arguments": {"path": "notes.md"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "gather.fetch", "arguments": {"url": origin + "/source"}}}]
    result = launch(root, workspace, requests, loopback_origins=json.dumps([origin]))
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [tool["name"] for tool in rows[0]["result"]["tools"]] == ["gather.docs", "gather.fetch"]
    assert rows[1]["result"]["isError"] is False, rows[1]
    docs = json.loads(rows[1]["result"]["content"][0]["text"])
    assert docs["verified"] is True and [row["id"] for row in docs["catalog"]] == ["notes.md"]
    assert rows[2]["result"]["isError"] is False, rows[2]
    assert json.loads(rows[2]["result"]["content"][0]["text"])["text"] == "Synthetic evidence: 14 records."
    assert hits == ["/source"]
