"""The ``gather federation`` CLI command (its own module, corpus_cmd precedent, so no
file exceeds the size budget). Validates a registry document or compiles its capture
plans; audits a policy-as-receipt document or an entity-resolution document, each sealed.
The machine payload is shared with the MCP surface through gather.payloads."""

from __future__ import annotations

import json
import sys

from gather.federation import RegistryError, registry_rows
from gather.federation_receipt import entity_candidates, policy_rules


def load_registry_file(path: str) -> list:
    """Read a registry JSON document from disk and normalize it to its raw rows."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return registry_rows(data)


def _load_json(path: str) -> object:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _registry_payload(args):
    from gather.payloads import federation_payload

    rows = registry_rows(_load_json(args.file))
    return federation_payload(rows, plan=(args.action == "plan"))


def _policy_payload(args):
    from gather.payloads import policy_payload

    return policy_payload(policy_rules(_load_json(args.file)))


def _entity_payload(args):
    from gather.payloads import entity_payload

    return entity_payload(entity_candidates(_load_json(args.file)))


def _build_payload(args) -> dict:
    if args.action in ("validate", "plan"):
        return _registry_payload(args)
    if args.action == "policy":
        return _policy_payload(args)
    return _entity_payload(args)


def _print_human(action: str, payload: dict) -> None:
    seal = payload["digest"]["seal"]
    if action == "policy":
        print(f"federation policy: {len(payload['rules'])} rule(s) valid; "
              f"seal {seal[:16]}...; verified {payload['verified']}")
        print("(a policy rule with no provenance capture is not evidence)")
        for r in payload["rules"]:
            print(f"  {r['rule']:<28} {r['failure_class']:<6} -> {r['verdict']}")
        return
    if action == "entity":
        res = payload["resolution"]
        print(f"federation entity: {len(res['candidates'])} candidate(s) valid; "
              f"seal {seal[:16]}...; verified {payload['verified']}")
        print(f"resolved {res['resolved']} on {res['identifier_path']} "
              f"(confidence {res['confidence']})")
        print("(a match with no named identifier_path is not an identity join)")
        return
    print(f"federation registry: {len(payload['sources'])} source row(s) valid; "
          f"seal {seal[:16]}...; verified {payload['verified']}")
    print("(a registry row is a catalog fact, not coverage and not availability)")
    for p in payload.get("plans", []):
        probe = "live-probe" if p["live_probe"] else "no-probe"
        print(f"  {p['id']:<24} {p['access']:<24} -> {p['action']} ({probe})")


def cmd_federation(args) -> int:
    try:
        payload = _build_payload(args)
    except FileNotFoundError:
        print(f"federation {args.action} failed: registry not found: {args.file}", file=sys.stderr)
        return 1
    except (RegistryError, json.JSONDecodeError, OSError) as exc:
        print(f"federation {args.action} failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    _print_human(args.action, payload)
    return 0
