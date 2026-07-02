"""The ``gather federation`` CLI command (its own module, corpus_cmd precedent, so no
file exceeds the size budget). Validates a registry document or compiles its capture
plans; the machine payload is shared with the MCP surface through gather.payloads."""

from __future__ import annotations

import json
import sys

from gather.federation import RegistryError, registry_rows


def load_registry_file(path: str) -> list:
    """Read a registry JSON document from disk and normalize it to its raw rows."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return registry_rows(data)


def cmd_federation(args) -> int:
    from gather.payloads import federation_payload

    try:
        rows = load_registry_file(args.file)
        payload = federation_payload(rows, plan=(args.action == "plan"))
    except FileNotFoundError:
        print(f"federation {args.action} failed: registry not found: {args.file}", file=sys.stderr)
        return 1
    except (RegistryError, json.JSONDecodeError, OSError) as exc:
        print(f"federation {args.action} failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    seal = payload["digest"]["seal"]
    print(f"federation registry: {len(payload['sources'])} source row(s) valid; "
          f"seal {seal[:16]}...; verified {payload['verified']}")
    print("(a registry row is a catalog fact, not coverage and not availability)")
    for p in payload.get("plans", []):
        probe = "live-probe" if p["live_probe"] else "no-probe"
        print(f"  {p['id']:<24} {p['access']:<24} -> {p['action']} ({probe})")
    return 0
