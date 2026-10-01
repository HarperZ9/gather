"""Every MCP tool states its title and read/write hints.

The Anthropic Software Directory Policy requires readOnlyHint, destructiveHint
and title on every tool a listed server exposes.
"""
from types import SimpleNamespace

from gather import client_mcp
from gather.mcp import TOOL_ANNOTATIONS, handle_request

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def _assert_complete(tools):
    assert tools
    for tool in tools:
        notes = tool["annotations"]
        assert notes["title"] and tool["title"] == notes["title"], tool["name"]
        assert all(isinstance(notes[key], bool) for key in HINTS), tool["name"]
        assert len(tool["name"]) <= 64
        if notes["readOnlyHint"]:
            assert notes["destructiveHint"] is False, tool["name"]


def test_full_surface_tools_are_annotated():
    tools = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    _assert_complete(tools)
    assert {tool["name"] for tool in tools} | {"gather.fetch"} == set(TOOL_ANNOTATIONS)


def test_client_profile_tools_are_annotated():
    _assert_complete(client_mcp.definitions())
    granted = client_mcp.definitions(SimpleNamespace(origins=frozenset({"https://example.org"})))
    _assert_complete(granted)
    by_name = {tool["name"]: tool["annotations"] for tool in granted}
    assert by_name["gather.docs"]["readOnlyHint"] is True
    assert by_name["gather.docs"]["openWorldHint"] is False
    assert by_name["gather.fetch"]["openWorldHint"] is True
