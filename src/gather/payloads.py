from __future__ import annotations

import json
from typing import Any

from gather.digest import digest, verify_digest
from gather.item import Item
from gather.source import Catalog

CATALOG_DIGEST_SCHEMA = "gather.catalog-digest/v1"
FEDERATION_SCHEMA = "gather.federation-registry/v1"
FEDERATION_POLICY_SCHEMA = "gather.federation-policy/v1"
FEDERATION_ENTITY_SCHEMA = "gather.federation-entity/v1"


def catalog_digest_payload(items: list[Item], *, dropped: int, stored: dict | None = None) -> dict[str, Any]:
    """Return the stable machine payload shared by CLI and MCP catalog/digest tools."""
    d = digest(items)
    cat = Catalog()
    cat.add(items)
    payload: dict[str, Any] = {
        "schema": CATALOG_DIGEST_SCHEMA,
        "catalog": cat.rows(),
        "digest": json.loads(d.to_json()),
        "verified": verify_digest(d),
        "dropped": dropped,
    }
    if stored is not None:
        payload["stored"] = stored
    return payload


def federation_payload(rows: list, *, plan: bool = False) -> dict[str, Any]:
    """The stable machine payload shared by the CLI and MCP federation surfaces.

    Carries the validated source rows and their sealed registry digest; with ``plan``
    it adds one compiled capture plan per source. Deliberately no coverage field, and
    none may be added: registry size is a catalog fact, never a coverage claim.
    """
    from gather.federation import registry_digest, validate_registry
    from gather.federation_policy import compile_plan

    sources = validate_registry(rows)
    d = registry_digest(sources)
    payload: dict[str, Any] = {
        "schema": FEDERATION_SCHEMA,
        "sources": sources,
        "digest": json.loads(d.to_json()),
        "verified": verify_digest(d),
    }
    if plan:
        payload["plans"] = [{"id": r["id"], **compile_plan(r["access"])} for r in sources]
    return payload


def policy_payload(rules: list) -> dict[str, Any]:
    """The stable machine payload for a policy-as-receipt document: each validated rule
    carries its provenance capture ref and its typed verdict, folded under one seal.
    A rule with no provenance, an unknown failure class, or a superseded flag is rejected
    upstream in ``validate_policy_rule``; this payload only ever carries admitted rules."""
    from gather.federation_receipt import policy_rule_digest, validate_policy_rule

    clean = [validate_policy_rule(r) for r in rules]
    d = policy_rule_digest(rules)
    return {
        "schema": FEDERATION_POLICY_SCHEMA,
        "rules": clean,
        "digest": json.loads(d.to_json()),
        "verified": verify_digest(d),
    }


def entity_payload(matches: list) -> dict[str, Any]:
    """The stable machine payload for an entity-resolution document: the ranked candidates,
    the resolution receipt (which candidate was promoted, on which identifier path), and the
    seal over every candidate. A ranking out of confidence order or a fuzzy-match promotion
    is rejected upstream in ``resolve_entity``; this payload only ever carries a real join."""
    from gather.federation_receipt import entity_match_digest, resolve_entity

    resolution = resolve_entity(matches)
    d = entity_match_digest(matches)
    return {
        "schema": FEDERATION_ENTITY_SCHEMA,
        "resolution": resolution,
        "digest": json.loads(d.to_json()),
        "verified": verify_digest(d),
    }