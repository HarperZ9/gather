from __future__ import annotations

import json
from typing import Any

from gather.digest import digest, verify_digest
from gather.item import Item
from gather.source import Catalog

CATALOG_DIGEST_SCHEMA = "gather.catalog-digest/v1"


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