"""Local client profile: launch-root confinement and explicit tool allowlist.

This is a read-only convenience boundary, not an OS sandbox. Concurrent local
filesystem mutation is outside its threat model. Full CLI/MCP remains separate.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

MAX_FILE = 8_000_000
MAX_ENTRIES = 20_000
NAME = "gather"
PACKAGE = "gather"


class ClientRefusal(ValueError):
    def __init__(self, detail, code="PATH_DENIED"):
        super().__init__(detail)
        self.code = code


def confined(root: Path, value: object, *, tree=False) -> Path:
    if not isinstance(value, str) or not value or chr(0) in value:
        raise ClientRefusal("path must be a non-empty string")
    # Reject Windows network/device/ADS paths before resolving or accessing them.
    text = value.replace(chr(92), "/")
    if text.startswith("//") or ":" in text[2:] or (":" in text and not (len(text) > 2 and text[1:3] == ":/")):
        raise ClientRefusal("network, device and alternate-stream paths are not permitted")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    path = candidate.resolve(strict=True)
    if path != root and root not in path.parents:
        raise ClientRefusal("path is outside the launch workspace")
    for part in [candidate, *candidate.parents]:
        if part == root.parent:
            break
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ClientRefusal("links and reparse points are not permitted")
    if path.is_file() and path.stat().st_size > MAX_FILE:
        raise ClientRefusal("file exceeds local client limit")
    if tree and path.is_dir():
        count = 0
        for folder, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"}]
            for name in [*dirs, *files]:
                count += 1
                if count > MAX_ENTRIES:
                    raise ClientRefusal("workspace exceeds local client entry limit")
                confined(root, str(Path(folder) / name))
    return path


def handle(req, root, network=None):
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    if "id" not in req:
        return None
    response = {"jsonrpc": "2.0", "id": req["id"]}
    method = req.get("method")
    if method == "initialize":
        from gather import __version__
        response["result"] = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                              "serverInfo": {"name": NAME + "-local", "version": __version__}}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": definitions(network)}
    elif method == "tools/call":
        try:
            params = req.get("params") or {}
            args = params.get("arguments") or {}
            name = params.get("name")
            definition = next((d for d in definitions(network) if d["name"] == name), None)
            if definition is None:
                raise ClientRefusal("tool requires the separately configured full MCP surface", "TOOL_NOT_GRANTED")
            if not isinstance(args, dict) or set(args) - set(definition["inputSchema"]["properties"]):
                raise ClientRefusal("unsupported arguments cannot grant permissions", "ARGUMENTS_DENIED")
            missing = set(definition["inputSchema"].get("required", [])) - set(args)
            if missing:
                raise ClientRefusal("missing required arguments", "ARGUMENTS_DENIED")
            data = network.get(args["url"]) if name == "gather.fetch" else invoke(name, dict(args), root)
            response["result"] = {"content": [{"type": "text", "text": data}], "isError": False}
        except Exception as exc:
            response["result"] = {"content": [{"type": "text", "text": json.dumps(
                {"code": exc.code if isinstance(exc, ClientRefusal) else "LOCAL_PROFILE_ERROR",
                 "detail": str(exc)})}], "isError": True}
    else:
        response["error"] = {"code": -32601, "message": "method not found"}
    return response


def install_process_boundary(network=None):
    """Deny process and network actions in this stdlib profile, including Git."""
    def audit(event, args):
        if event.startswith("socket."):
            if network is None:
                raise PermissionError("local client profile does not grant network")
            network.audit_socket(event, args)
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.posix_spawnp",
                     "os.exec", "os.spawn"}:
            raise PermissionError("local client profile does not grant processes or network")
    sys.addaudithook(audit)


def origin_array(value):
    """Parse desktop setup text without interpreting it as flags or authority."""
    if not value.strip():
        return []
    try:
        values = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("origin setting must be a JSON array of strings") from exc
    if not isinstance(values, list) or any(not isinstance(entry, str) for entry in values):
        raise argparse.ArgumentTypeError("origin setting must be a JSON array of strings")
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="explicit local directory this client may read")
    parser.add_argument("--allow-origin", action="append", default=[], help="allow GET from this exact public HTTPS origin")
    parser.add_argument("--allow-loopback-origin", action="append", default=[], help="allow GET from this exact literal loopback HTTP(S) origin")
    parser.add_argument("--allow-origins-json", type=origin_array, default=[], help="desktop setup JSON array of public HTTPS origins; empty means none")
    parser.add_argument("--allow-loopback-origins-json", type=origin_array, default=[], help="desktop setup JSON array of literal loopback origins; empty means none")
    args = parser.parse_args(argv)
    root_arg = Path(args.workspace).absolute()
    root = confined(root_arg, str(root_arg))
    if not root.is_dir():
        parser.error("workspace must be a directory")
    from gather.client_network import NetworkGrant
    try:
        network = NetworkGrant.from_launch([*args.allow_origin, *args.allow_origins_json],
                                           [*args.allow_loopback_origin, *args.allow_loopback_origins_json])
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    install_process_boundary(network)
    # The local profile does not read permission grants from the environment.
    for line in sys.stdin:
        if len(line) > MAX_FILE:
            return 2
        try:
            response = handle(json.loads(line), root, network)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "parse error"}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0

def definitions(network=None):
    from gather.mcp import _tool_defs
    tools = [d for d in _tool_defs() if d["name"] in {"gather.docs"}]
    if network is not None and network.origins:
        tools.append({"name": "gather.fetch", "description": "Read an allowed origin; return untrusted source text and a byte receipt. No redirects or credentials.",
                      "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False}})
    return tools


def invoke(name, args, root):
    from gather.grants import NONE
    from gather.mcp import call_tool
    # Single files avoid a directory walk following a file link outside the grant.
    path = confined(root, args["path"])
    if not path.is_file():
        raise ClientRefusal("local client intake requires one text file per call")
    args["path"] = str(path)
    return call_tool(name, args, grants=NONE)


if __name__ == "__main__":
    raise SystemExit(main())
