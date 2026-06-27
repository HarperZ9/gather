from __future__ import annotations

import json

from gather import __version__

SCHEMA = "project-telos.flagship-action/v1"
TOOL = "gather"
PRIMARY_COMMANDS = ["docs", "web", "feed", "pdf", "run", "corpus"]


def envelope(command: str, *, status: str = "MATCH", native: dict | None = None,
             next_actions: list[dict] | None = None,
             diagnostics: list[dict] | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "tool": TOOL,
        "tool_version": __version__,
        "command": command,
        "status": status,
        "inputs": [],
        "outputs": [],
        "receipts": [],
        "native": native or {},
        "next_actions": next_actions or [],
        "diagnostics": diagnostics or [],
    }


def _next(tool: str, action: str, reason: str) -> dict:
    return {"tool": tool, "action": action, "reason": reason, "inputs": [], "priority": "normal"}


def status_payload() -> dict:
    return envelope(
        "status",
        native={"role": "perception-intake", "commands": PRIMARY_COMMANDS},
        next_actions=[_next("index", "map", "map workspace context for gathered sources")],
    )


def doctor_payload() -> dict:
    checks = [
        {"name": "zero_dependency_core", "status": "MATCH"},
        {"name": "json_receipts", "status": "MATCH"},
        {"name": "offline_docs_intake", "status": "MATCH"},
    ]
    return envelope(
        "doctor",
        native={"checks": checks},
        next_actions=[_next("crucible", "assess", "verify repeated claims from gathered sources")],
    )


def demo_payload() -> dict:
    return envelope(
        "demo",
        native={"command": "gather docs <path> --json"},
        next_actions=[_next("forum", "route", "route the next action after intake")],
    )


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status={payload['status']} tool={payload['tool']} command={payload['command']}")
        for action in payload["next_actions"]:
            print(f"next: {action['tool']} {action['action']} - {action['reason']}")
    return 0


def cmd_status(args) -> int:
    return emit(status_payload(), args.json)


def cmd_doctor(args) -> int:
    return emit(doctor_payload(), args.json)


def cmd_demo(args) -> int:
    return emit(demo_payload(), args.json)
