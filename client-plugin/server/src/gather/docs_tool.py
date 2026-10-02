"""The gather.docs tool and the MCP tool annotations.

Shared by the full MCP server and the local client profile, so the client can
serve gather.docs without importing the full tool surface.
"""
from __future__ import annotations

import json

from gather.localpath import require_local
from gather.payloads import catalog_digest_payload
from gather.scope import filter_scope


def scope_terms(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [term.strip() for term in raw.split(",") if term.strip()]
    if isinstance(raw, list) and all(isinstance(term, str) for term in raw):
        return [term.strip() for term in raw if term.strip()]
    raise ValueError("scope must be a comma-separated string or a list of strings")


def payload_from_items(items, scope: list[str]) -> dict:
    kept, dropped = filter_scope(items, scope)
    return catalog_digest_payload(kept, dropped=dropped)


def _hints(title: str, *, read_only: bool = True, idempotent: bool = True,
           open_world: bool = False) -> dict:
    return {"title": title, "readOnlyHint": read_only, "destructiveHint": False,
            "idempotentHint": idempotent, "openWorldHint": open_world}


# MCP tool annotations. A hint describes the tool to the client and grants
# nothing; launch grants still refuse network sources, commands and credentials.
TOOL_ANNOTATIONS = {
    "gather.status": _hints("Gather status"),
    "gather.doctor": _hints("Gather readiness check"),
    "gather.docs": _hints("Read local documents with receipts"),
    "gather.arxiv": _hints("Fetch arXiv metadata", idempotent=False, open_world=True),
    "gather.federation": _hints("Validate or plan a source registry"),
    "gather.run": _hints("Run a gather config", read_only=False, idempotent=False,
                         open_world=True),
    "gather.context": _hints("Select verified corpus context"),
    "gather.pilot": _hints("Run or verify a gather pilot", read_only=False, idempotent=False,
                           open_world=True),
    "gather.fetch": _hints("Read an allowed web origin", idempotent=False, open_world=True),
}


def annotate(tool: dict) -> dict:
    notes = dict(TOOL_ANNOTATIONS[tool["name"]])
    return {**tool, "title": notes["title"], "annotations": notes}


def docs_tool() -> dict:
    """The raw gather.docs definition, before annotation."""
    return {
        "name": "gather.docs",
        "description": "Read a local text file or directory and return catalog rows plus digest receipts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "local file or directory to read; a network "
                                                          "or device path returns NON_LOCAL_PATH"},
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
    }


def call_docs(args: dict) -> str:
    """Run gather.docs: read one local path and return catalog rows plus digest receipts."""
    from gather.docs import DocsSource

    path = args.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("gather.docs requires a non-empty path")
    require_local(path, label="path")
    payload = payload_from_items(DocsSource().fetch(path), scope_terms(args.get("scope")))
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
