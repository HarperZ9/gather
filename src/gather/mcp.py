from __future__ import annotations

import json
import sys
from typing import Any

from gather import __version__
from gather.digest import digest
from gather.flagship import doctor_payload, status_payload
from gather.scope import filter_scope
from gather.source import Catalog

MCP_PROTOCOL_VERSION = "2025-06-18"


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _scope_terms(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [term.strip() for term in raw.split(",") if term.strip()]
    if isinstance(raw, list) and all(isinstance(term, str) for term in raw):
        return [term.strip() for term in raw if term.strip()]
    raise ValueError("scope must be a comma-separated string or a list of strings")


def _payload_from_items(items, scope: list[str]) -> dict:
    kept, dropped = filter_scope(items, scope)
    cat = Catalog()
    cat.add(kept)
    return {
        "catalog": cat.rows(),
        "digest": json.loads(digest(kept).to_json()),
        "dropped": dropped,
    }


def _tool_defs() -> list[dict]:
    return [
        {
            "name": "gather.status",
            "description": "Emit Gather's Project Telos operator-spine status envelope.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "gather.doctor",
            "description": "Check Gather's operator-spine readiness envelope.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "gather.docs",
            "description": "Read a local text file or directory and return catalog rows plus digest receipts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "file or directory to read"},
                    "scope": {
                        "description": "optional comma-separated string or list of scope terms",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "gather.arxiv",
            "description": "Fetch current arXiv metadata by id or query and return catalog rows plus digest receipts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "arXiv id or free-text query"},
                    "max_results": {"type": "integer", "description": "maximum search results", "minimum": 1},
                    "scope": {
                        "description": "optional comma-separated string or list of scope terms",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "gather.run",
            "description": "Run a multi-source gather config and return the witnessed run record.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": {"type": "string", "description": "path to a gather run JSON config"},
                },
                "required": ["config"],
            },
        },
    ]


def call_tool(name: str, args: dict) -> str:
    if name == "gather.status":
        return json.dumps(status_payload(), indent=2, sort_keys=True)
    if name == "gather.doctor":
        return json.dumps(doctor_payload(), indent=2, sort_keys=True)
    if name == "gather.docs":
        from gather.docs import DocsSource

        path = args.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("gather.docs requires a non-empty path")
        payload = _payload_from_items(DocsSource().fetch(path), _scope_terms(args.get("scope")))
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    if name == "gather.arxiv":
        from gather.arxiv import ArxivSource

        query = args.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError("gather.arxiv requires a non-empty query")
        max_results = int(args.get("max_results", 10))
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload = _payload_from_items(
            ArxivSource(max_results=max_results).fetch(query),
            _scope_terms(args.get("scope")),
        )
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    if name == "gather.run":
        from gather.run_config import load_run_config, plan_from_config, run_plan

        config = args.get("config")
        if not isinstance(config, str) or not config:
            raise ValueError("gather.run requires a non-empty config path")
        try:
            cfg = load_run_config(config)
            plan = plan_from_config(cfg)
        except FileNotFoundError as exc:
            raise ValueError(f"config not found: {config}") from exc
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"bad config: {exc}") from exc
        record, _items = run_plan(plan)
        return json.dumps(record.to_dict(), indent=2, ensure_ascii=False)
    raise ValueError(f"unknown tool: {name}")


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    mid = req.get("id")

    if "id" not in req:
        return None
    if method == "initialize":
        return _ok(mid, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gather", "version": __version__},
        })
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": _tool_defs()})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str) or name not in {tool["name"] for tool in _tool_defs()}:
            return _err(mid, -32602, f"unknown tool: {name!r}")
        try:
            text = call_tool(name, params.get("arguments") or {})
            return _ok(mid, _text_result(text))
        except Exception as exc:
            return _ok(mid, _text_result(f"error: {exc}", is_error=True))
    return _err(mid, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        response = handle_request(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0
