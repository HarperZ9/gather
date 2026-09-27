"""File sources and MCP path arguments refuse Windows network and device paths.

On Windows, opening ``\\\\host\\share\\x`` connects to ``host`` over SMB and can send the user's
NTLM credentials to it. ``\\\\.\\``, ``\\\\?\\``, ``\\??\\`` and reserved names such as ``CON``
open devices or skip normal path handling. Each test hands a source or an MCP tool one of those
paths with the filesystem layer replaced by a spy, so no test here reaches the network or a device.
A refused path raises before the spy sees it. Before the fix every source passed the path through.
"""
import builtins
import io
import os
import subprocess

import pytest

import gather.context  # noqa: F401 - bound before any test replaces gather.store.Corpus
import gather.docs as docs_mod
import gather.ocr as ocr_mod
import gather.pdf as pdf_mod
import gather.pilot  # noqa: F401
import gather.run  # noqa: F401
import gather.store as store_mod
import gather.transcribe as transcribe_mod
from gather.docs import DocsSource
from gather.mcp import handle_request
from gather.ocr import OcrSource
from gather.pdf import PdfSource
from gather.transcribe import TranscribeSource

BS = "\\"
HOST = "attacker.invalid"

# Windows-style text: refused on every platform.
UNC = [
    BS * 2 + HOST + BS + "share" + BS + "doc.md",
    "//" + HOST + "/share/doc.md",
    "/" + BS + HOST + BS + "share" + BS + "doc.md",
    BS + "/" + HOST + "/share/doc.md",
    "  " + BS * 2 + HOST + BS + "share" + BS + "doc.md",
]
NAMESPACE = [
    BS * 2 + "?" + BS + "C:" + BS + "Windows" + BS + "win.ini",
    BS * 2 + "." + BS + "C:" + BS + "Windows" + BS + "win.ini",
    BS * 2 + "?" + BS + "UNC" + BS + HOST + BS + "share" + BS + "doc.md",
    BS * 2 + "?" + BS + "uNc" + BS + HOST + BS + "share" + BS + "doc.md",
    BS * 2 + "." + BS + "UNC" + BS + HOST + BS + "share" + BS + "doc.md",
    BS * 2 + "?" + BS + "GLOBALROOT" + BS + "Device" + BS + "Mup" + BS + HOST + BS + "share" + BS + "doc.md",
    BS * 2 + "." + BS + "PhysicalDrive0",
    BS * 2 + "." + BS + "pipe" + BS + "gather",
    "//?/C:/Windows/win.ini",
    "/" + BS + "?" + BS + "UNC" + BS + HOST + BS + "share",
    BS + "??" + BS + "C:" + BS + "Windows" + BS + "win.ini",
    BS + "??" + BS + "UNC" + BS + HOST + BS + "share" + BS + "doc.md",
]
DEVICE = [
    "C:" + BS + "Temp" + BS + "NUL",
    "C:/Temp/CON",
    "C:NUL",
    "notes" + BS + "PRN.md",
    "notes" + BS + "aux.tar.gz",
    "notes" + BS + "cOn",
    "notes" + BS + "nUl.TxT",
    "notes" + BS + "COM1",
    "notes" + BS + "com9.log",
    "notes" + BS + "LPT1",
    "notes" + BS + "Lpt9.md",
    "notes" + BS + "COM\u00b9",
    "notes" + BS + "CONIN$",
    "notes" + BS + "NUL.",
    "notes" + BS + "CON ",
    "notes" + BS + "aux . .",
    "notes" + BS + "NUL:",
    "notes" + BS + ".." + BS + "NUL",
    "." + BS + "CON",
    "sub" + BS + ".." + BS + ".." + BS + "aux.md",
    "a/b" + BS + ".." + BS + ".." + BS + "PRN",
]
REFUSED = UNC + NAMESPACE + DEVICE
# POSIX-style device names: Windows rules apply on Windows only; on POSIX these are ordinary names.
POSIX_STYLE_DEVICE = ["CON", "nul.txt", "docs/../NUL", "./COM1.log", "a/b/../../PRN"]


class Spy:
    """Stands in for the filesystem and the child-process layer, for the one probe path only."""

    def __init__(self, monkeypatch, probe):
        self.probe, self.touched = probe, []
        real_isfile, real_isdir, real_realpath = os.path.isfile, os.path.isdir, os.path.realpath

        def isfile(path):
            return self._hit("isfile", path, True) if self._is_probe(path) else real_isfile(path)

        def isdir(path):
            return self._hit("isdir", path, False) if self._is_probe(path) else real_isdir(path)

        def realpath(path, *args, **kwargs):
            return self._hit("realpath", path, path) if self._is_probe(path) else real_realpath(path, *args, **kwargs)

        def fake_open(path, *args, **kwargs):
            if self._is_probe(path):
                return self._hit("open", path, io.StringIO("planted body"))
            return builtins.open(path, *args, **kwargs)

        def run_tool(program, args, **kwargs):
            self.touched.append(("run_tool", program))
            return subprocess.CompletedProcess(args, 0, b"planted body", b"")

        monkeypatch.setattr(os.path, "isfile", isfile)
        monkeypatch.setattr(os.path, "isdir", isdir)
        monkeypatch.setattr(os.path, "realpath", realpath)
        monkeypatch.setattr(docs_mod, "open", fake_open, raising=False)
        for module in (pdf_mod, ocr_mod, transcribe_mod):
            monkeypatch.setattr(module, "run_tool", run_tool)

    def _is_probe(self, path):
        return isinstance(path, (str, os.PathLike)) and os.fspath(path) == self.probe

    def _hit(self, what, path, result):
        self.touched.append((what, os.fspath(path)))
        return result


SOURCES = {
    "docs": DocsSource,
    "pdf": PdfSource,
    "ocr": OcrSource,
    "transcribe": TranscribeSource,
}


def _assert_refused(exc_info, spy):
    assert getattr(exc_info.value, "code", None) == "NON_LOCAL_PATH", exc_info.value
    assert spy.touched == [], f"the source reached the filesystem layer first: {spy.touched}"


@pytest.mark.parametrize("path", REFUSED)
def test_docs_source_refuses_network_and_device_paths(monkeypatch, path):
    spy = Spy(monkeypatch, path)
    with pytest.raises(ValueError) as exc_info:
        DocsSource().fetch(path)
    _assert_refused(exc_info, spy)


@pytest.mark.parametrize("name", ["pdf", "ocr", "transcribe"])
@pytest.mark.parametrize("path", [UNC[0], UNC[1], NAMESPACE[0], NAMESPACE[2], NAMESPACE[10], DEVICE[0], DEVICE[17]])
def test_tool_sources_refuse_network_and_device_paths(monkeypatch, name, path):
    spy = Spy(monkeypatch, path)
    with pytest.raises(ValueError) as exc_info:
        SOURCES[name]().fetch(path)
    _assert_refused(exc_info, spy)


@pytest.mark.parametrize("path", POSIX_STYLE_DEVICE)
def test_posix_style_device_names_follow_the_host_rules(monkeypatch, path):
    spy = Spy(monkeypatch, path)
    if os.name == "nt":
        with pytest.raises(ValueError) as exc_info:
            DocsSource().fetch(path)
        _assert_refused(exc_info, spy)
    else:
        items = DocsSource().fetch(path)  # an ordinary file name on POSIX
        assert [i.text for i in items] == ["planted body"]


def test_docs_source_still_reads_a_local_file(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("local text\n", encoding="utf-8")
    items = DocsSource().fetch(str(note))
    assert [i.text for i in items] == ["local text\n"]


def test_cli_docs_refuses_a_unc_path(monkeypatch, capsys):
    from gather.cli import main

    spy = Spy(monkeypatch, UNC[0])
    assert main(["docs", UNC[0]]) == 1
    assert "network" in capsys.readouterr().err
    assert spy.touched == []


# --- MCP surface --------------------------------------------------------------------------------

def _call(name, arguments):
    req = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    return handle_request(req)


def _refusal(resp):
    result = resp["result"]
    assert result.get("isError") is True, result
    body = result.get("structuredContent")
    assert body is not None, f"no structured refusal: {result}"
    assert body["code"] == "NON_LOCAL_PATH" and body["retryable"] is False
    return body


@pytest.fixture
def opened(monkeypatch):
    """Replace every path-opening helper the MCP tools call with a recorder that fails loudly."""
    calls = []

    def recorder(label):
        def _record(*args, **kwargs):
            calls.append(label)
            raise RuntimeError(f"{label} was called")
        return _record

    targets = {
        "gather.run_config.load_run_config": "load_run_config",
        "gather.federation_cmd.load_registry_file": "load_registry_file",
        "gather.context.inspect_corpus": "inspect_corpus",
        "gather.context.select_context": "select_context",
        "gather.pilot_manifest.load_pilot_manifest": "load_pilot_manifest",
        "gather.pilot.run_pilot": "run_pilot",
        "gather.pilot.refresh_pilot": "refresh_pilot",
        "gather.pilot.verify_pilot": "verify_pilot",
        "gather.pilot_bundle.create_pilot_bundle": "create_pilot_bundle",
    }
    for target, label in targets.items():
        monkeypatch.setattr(target, recorder(label))
    return calls


@pytest.mark.parametrize("path", [UNC[0], UNC[1], NAMESPACE[2], NAMESPACE[10], DEVICE[0]])
def test_mcp_docs_refuses_network_and_device_paths(monkeypatch, path):
    spy = Spy(monkeypatch, path)
    body = _refusal(_call("gather.docs", {"path": path}))
    assert body["argument"] == "path"
    assert spy.touched == []


@pytest.mark.parametrize(("tool", "arguments", "argument"), [
    ("gather.run", {"config": UNC[0]}, "config"),
    ("gather.run", {"config_path": NAMESPACE[2]}, "config"),
    ("gather.federation", {"action": "validate", "registry": UNC[1]}, "registry"),
    ("gather.context", {"corpus": UNC[0]}, "corpus"),
    ("gather.context", {"corpus": NAMESPACE[5], "select": ["row_x"], "expected_corpus_digest": "d"}, "corpus"),
    ("gather.pilot", {"action": "run", "manifest": UNC[0], "output": "out"}, "manifest"),
    ("gather.pilot", {"action": "verify", "output": UNC[1]}, "output"),
    ("gather.pilot", {"action": "refresh", "output": NAMESPACE[10]}, "output"),
    ("gather.pilot", {"action": "bundle", "output": "out", "bundle_output": UNC[0], "visibility": "shared"},
     "bundle_output"),
])
def test_mcp_path_arguments_refuse_network_paths(opened, tool, arguments, argument):
    body = _refusal(_call(tool, arguments))
    assert body["argument"] == argument
    assert opened == [], f"the tool opened the path first: {opened}"


def test_mcp_run_refuses_a_file_source_target_before_anything_runs(monkeypatch, opened):
    spy = Spy(monkeypatch, UNC[0])
    config = {"jobs": [{"source": "docs", "target": UNC[0]}]}
    body = _refusal(_call("gather.run", {"config": config}))
    assert body["argument"] == "jobs[0].target"
    assert spy.touched == [] and opened == []


def test_mcp_run_refuses_a_network_store(monkeypatch, tmp_path, opened):
    def corpus(root):
        opened.append(("Corpus", root))
        raise RuntimeError("Corpus was built")

    monkeypatch.setattr(store_mod, "Corpus", corpus)
    note = tmp_path / "note.md"
    note.write_text("local text\n", encoding="utf-8")
    config = {"jobs": [{"source": "docs", "target": str(note)}], "store": UNC[0]}
    body = _refusal(_call("gather.run", {"config": config}))
    assert body["argument"] == "store"
    assert opened == []
