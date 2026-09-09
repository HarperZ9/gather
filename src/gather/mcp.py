from __future__ import annotations

import json
import sys
from typing import Any

from gather import __version__
from gather.flagship import doctor_payload, status_payload
from gather.payloads import catalog_digest_payload
from gather.scope import filter_scope

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
    return catalog_digest_payload(kept, dropped=dropped)


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
                        "description": (
                            "optional post-fetch content filter: keep items whose title or body "
                            "contains any term as a case-insensitive substring; omit for unfiltered capture"
                        ),
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
                        "description": (
                            "optional post-fetch content filter: keep items whose title or body "
                            "contains any term as a case-insensitive substring; omit for unfiltered capture"
                        ),
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
            "name": "gather.federation",
            "description": "Validate a source-federation registry or compile its capture plans; "
                           "returns the sealed registry payload.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["validate", "plan"]},
                    "registry": {
                        "description": "inline registry rows (or {sources:[...]}) or a path to a registry JSON file",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "object"},
                            {"type": "array"},
                        ],
                    },
                },
                "required": ["action", "registry"],
            },
        },
        {
            "name": "gather.run",
            "description": "Run a multi-source gather config and return the witnessed run record.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": {
                        "description": "inline gather run JSON config or path to a config file",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "object"},
                        ],
                    },
                    "config_path": {"type": "string", "description": "path to a gather run JSON config"},
                },
            },
        },
        {
            "name": "gather.context",
            "description": "Inspect bounded readable corpus excerpts or select verified rows into a private context payload.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "corpus": {"type": "string", "description": "stored Gather corpus directory"},
                    "select": {
                        "description": "optional selections as ROW_REF[:START[:LIMIT]] strings or objects",
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "row_ref": {"type": "string"},
                                        "start": {"type": "integer", "minimum": 0},
                                        "limit": {"type": "integer", "minimum": 1},
                                    },
                                    "required": ["row_ref"],
                                },
                            ]
                        },
                    },
                    "expected_corpus_digest": {"type": "string"},
                    "max_rows": {"type": "integer", "minimum": 1},
                    "excerpt_chars": {"type": "integer", "minimum": 1},
                    "max_total_chars": {"type": "integer", "minimum": 1},
                    "max_catalog_bytes": {"type": "integer", "minimum": 1},
                    "max_catalog_rows": {"type": "integer", "minimum": 1},
                    "max_body_bytes": {"type": "integer", "minimum": 1},
                    "max_read_bytes": {"type": "integer", "minimum": 1},
                },
                "required": ["corpus"],
            },
        },
        {
            "name": "gather.pilot",
            "description": "Run, refresh, verify, or bundle a controlled Gather pilot.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["run", "refresh", "verify", "bundle"]},
                    "manifest": {
                        "description": "inline pilot manifest object or path to a manifest JSON file",
                        "oneOf": [{"type": "string"}, {"type": "object"}],
                    },
                    "output": {"type": "string", "description": "pilot evidence root directory"},
                    "bundle_output": {"type": "string", "description": "bundle ZIP path (bundle action)"},
                    "visibility": {"type": "string", "enum": ["shared", "full"]},
                    "include_private_evidence": {"type": "boolean"},
                },
                "required": ["action", "output"],
            },
        },
    ]


def _federation_tool(args: dict) -> str:
    from gather.federation import registry_rows
    from gather.federation_cmd import load_registry_file
    from gather.payloads import federation_payload

    action = args.get("action")
    if action not in ("validate", "plan"):
        raise ValueError("gather.federation action must be 'validate' or 'plan'")
    registry = args.get("registry")
    if isinstance(registry, str) and registry:
        try:
            rows = load_registry_file(registry)
        except FileNotFoundError as exc:
            raise ValueError(f"registry not found: {registry}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad registry: {exc}") from exc
    elif isinstance(registry, (list, dict)):
        rows = registry_rows(registry)
    else:
        raise ValueError("gather.federation requires registry rows or a non-empty registry path")
    payload = federation_payload(rows, plan=(action == "plan"))
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _pilot_tool(args: dict) -> str:
    from pathlib import Path

    from gather.pilot import refresh_pilot, run_pilot, verify_pilot
    from gather.pilot_bundle import create_pilot_bundle, verify_pilot_bundle
    from gather.pilot_manifest import load_pilot_manifest, validate_pilot_manifest

    action = args.get("action")
    output = args.get("output")
    if action not in ("run", "refresh", "verify", "bundle"):
        raise ValueError(f"gather.pilot action must be run, refresh, verify, or bundle (got {action!r})")
    if not isinstance(output, str) or not output:
        raise ValueError("gather.pilot requires a non-empty output")

    if action == "run":
        manifest = args.get("manifest")
        if isinstance(manifest, dict):
            validated = validate_pilot_manifest(manifest, Path.cwd())
        elif isinstance(manifest, str) and manifest:
            validated = load_pilot_manifest(manifest)
        else:
            raise ValueError("gather.pilot run requires a manifest object or path")
        result = run_pilot(validated, Path(output))
        return json.dumps(
            {
                "action": "run",
                "manifest_digest": result.manifest_sha256,
                "source_outcomes": [o.to_dict() for o in result.source_outcomes],
                "corpus_verified": result.corpus_verified,
            },
            indent=2,
            sort_keys=True,
        )
    if action == "refresh":
        result = refresh_pilot(Path(output))
        return json.dumps(
            {"action": "refresh", "monitor_report": result.monitor_report},
            indent=2,
            sort_keys=True,
        )
    if action == "verify":
        verification = verify_pilot(Path(output))
        return json.dumps(
            {"action": "verify", "ok": verification.ok, "checks": verification.to_dict()},
            indent=2,
            sort_keys=True,
        )
    # bundle
    bundle_output = args.get("bundle_output")
    visibility = args.get("visibility")
    if visibility not in ("shared", "full"):
        raise ValueError("gather.pilot bundle requires visibility shared or full")
    if not isinstance(bundle_output, str) or not bundle_output:
        raise ValueError("gather.pilot bundle requires a bundle_output path")
    receipt = create_pilot_bundle(
        Path(output),
        Path(bundle_output),
        visibility=visibility,
        include_private_evidence=bool(args.get("include_private_evidence", False)),
    )
    return json.dumps(
        {
            "action": "bundle",
            "visibility": receipt.visibility,
            "bundle_digest": receipt.bundle_digest,
            "verified": verify_pilot_bundle(Path(bundle_output)).ok,
        },
        indent=2,
        sort_keys=True,
    )


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
    if name == "gather.federation":
        return _federation_tool(args)
    if name == "gather.context":
        from gather.context import inspect_corpus, select_context

        corpus = args.get("corpus")
        if not isinstance(corpus, str) or not corpus:
            raise ValueError("gather.context requires a non-empty corpus")
        selections = args.get("select")
        if selections is None:
            payload = inspect_corpus(
                corpus,
                max_rows=args.get("max_rows"),
                excerpt_chars=args.get("excerpt_chars"),
                max_catalog_bytes=args.get("max_catalog_bytes"),
                max_catalog_rows=args.get("max_catalog_rows"),
                max_body_bytes=args.get("max_body_bytes"),
                max_read_bytes=args.get("max_read_bytes"),
            )
        elif isinstance(selections, list):
            expected = args.get("expected_corpus_digest")
            if not isinstance(expected, str) or not expected:
                raise ValueError("gather.context selection requires expected_corpus_digest")
            payload = select_context(
                corpus,
                selections,
                expected_corpus_digest=expected,
                max_rows=args.get("max_rows"),
                max_total_chars=args.get("max_total_chars"),
                max_catalog_bytes=args.get("max_catalog_bytes"),
                max_catalog_rows=args.get("max_catalog_rows"),
                max_body_bytes=args.get("max_body_bytes"),
                max_read_bytes=args.get("max_read_bytes"),
            )
        else:
            raise ValueError("gather.context select must be an array")
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    if name == "gather.run":
        from gather.run_config import load_run_config, plan_from_config, run_plan

        config = args.get("config")
        if config is None:
            config = args.get("config_path")
        if isinstance(config, str) and config:
            try:
                cfg = load_run_config(config)
            except FileNotFoundError as exc:
                raise ValueError(f"config not found: {config}") from exc
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"bad config: {exc}") from exc
        elif isinstance(config, dict):
            cfg = config
        else:
            raise ValueError("gather.run requires config as an inline object or non-empty config path")
        try:
            plan = plan_from_config(cfg)
        except (ValueError, KeyError) as exc:
            raise ValueError(f"bad config: {exc}") from exc
        record, _items = run_plan(plan)
        return json.dumps(record.to_dict(), indent=2, ensure_ascii=False)
    if name == "gather.pilot":
        return _pilot_tool(args)
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
