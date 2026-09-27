"""Which bare names Windows maps to a device, and which names gather refuses as one.

Windows maps ``COM1`` to ``COM9`` and ``LPT1`` to ``LPT9``, and the superscript forms of 1, 2
and 3, to devices. It never maps ``COM0`` or ``LPT0``: those are ordinary file names, and a
folder that holds ``COM0.md`` must read like any other folder. The last test asks Windows itself
through ``GetFullPathNameW``, so the name table cannot drift from what the host does.
"""
import json
import ntpath
import os

import pytest

from gather.docs import DocsSource
from gather.localpath import _RESERVED, DEVICE, classify
from gather.mcp import handle_request

BS = "\\"
ZERO_PORTS = ["COM0", "LPT0", "com0.md", "Lpt0.txt", "COM0 ", "LPT0.", "COM0:stream"]
NUMBERED_PORTS = [f"{port}{n}" for port in ("COM", "LPT") for n in "123456789\u00b9\u00b2\u00b3"]
# The names at the edge of the COM and LPT families, where gather must agree with Windows exactly.
BOUNDARY = ["COM0", "LPT0", "COM1", "LPT1", "COM9", "LPT9", "COM10", "LPT10", "COM", "LPT"]


@pytest.mark.parametrize("name", ZERO_PORTS)
def test_com0_and_lpt0_are_ordinary_names(name):
    assert classify(name, windows=True) is None
    assert classify(BS.join(["C:", "docs", name])) is None
    assert classify("docs/" + name, windows=True) is None


@pytest.mark.parametrize("name", NUMBERED_PORTS)
def test_the_numbered_ports_stay_devices(name):
    assert classify(name, windows=True) == DEVICE
    assert classify(BS.join(["docs", name.lower() + ".md"])) == DEVICE


def test_a_docs_folder_with_com0_and_lpt0_files_reads(tmp_path):
    (tmp_path / "COM0.md").write_text("zero port\n", encoding="utf-8")
    (tmp_path / "LPT0").mkdir()
    (tmp_path / "LPT0" / "inside.md").write_text("inside a folder named LPT0\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("plain\n", encoding="utf-8")
    items = DocsSource().fetch(str(tmp_path))
    assert sorted((i.title, i.text) for i in items) == [
        ("COM0.md", "zero port\n"),
        ("LPT0/inside.md", "inside a folder named LPT0\n"),
        ("notes.md", "plain\n"),
    ]
    assert [i.text for i in DocsSource().fetch(str(tmp_path / "COM0.md"))] == ["zero port\n"]


def test_the_mcp_docs_tool_reads_a_com0_file(tmp_path):
    source = tmp_path / "LPT0.md"
    source.write_text("a legitimate file name\n", encoding="utf-8")
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "gather.docs", "arguments": {"path": str(source)}}}
    result = handle_request(req)["result"]
    assert not result.get("isError"), result
    body = json.loads(result["content"][0]["text"])
    assert body["verified"] is True
    assert body["digest"]["receipts"][0]["title"] == "LPT0.md"


def _manifest(target):
    return {
        "schema": "gather.pilot-manifest/1", "pilot_id": "p", "title": "t", "mode": "offline",
        "deployment": {"mode": "workstation", "custodian": "customer"},
        "policy": {"allowed_hosts": [], "trusted_browser_hosts": [], "allowed_local_roots": ["fixtures"],
                   "enabled_adapters": ["docs"], "credentials": [], "report_private_content": False},
        "missions": [{"id": "m", "title": "m", "sources": [{
            "id": "s", "adapter": "docs", "target": target, "fixture": None, "refresh_fixture": None,
            "visibility": "private", "monitor": False, "required": True, "extraction": None, "options": {}}]}],
    }


def test_a_pilot_manifest_may_name_com0_on_every_platform(tmp_path):
    from gather.pilot_manifest import validate_pilot_manifest

    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "COM0.md").write_text("a note\n", encoding="utf-8")
    manifest = validate_pilot_manifest(_manifest("fixtures/COM0.md"), tmp_path)
    assert manifest.missions[0].sources[0].target == "fixtures/COM0.md"


@pytest.mark.skipif(os.name != "nt", reason="asks Windows which names it maps to a device")
def test_the_reserved_names_track_what_windows_maps_to_a_device():
    device_prefix = BS * 2 + "." + BS  # GetFullPathNameW turns a device name into \\.\NAME

    def windows_maps(name):
        return ntpath.abspath(name).startswith(device_prefix)

    missed = [n for n in sorted(_RESERVED | set(BOUNDARY)) if windows_maps(n) and classify(n, windows=True) != DEVICE]
    assert missed == [], "Windows opens these as devices, so gather must refuse them"
    wrong = [n for n in BOUNDARY if (classify(n, windows=True) == DEVICE) != windows_maps(n)]
    assert wrong == [], "at the edge of the COM and LPT families gather must agree with Windows"
