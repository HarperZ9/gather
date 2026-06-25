from __future__ import annotations

import json
from typing import Protocol

from gather.item import Item


class Source(Protocol):
    """An intake adapter: ingests Items from one kind of source.

    This is the isolated impure edge. An adapter may use the network, a third-party
    tool, or credentials, but it hides all of that behind this one shape, so the rest
    of Gather stays clean and the awkwardness of a source is an adapter problem, not a
    system problem. Gather never imports an adapter's internals, only this shape.

    ``fetch(target)`` is the RETRIEVAL seam: one string in, items out, each fingerprinting
    the content it retrieved. Synthesis (deriving a fact from several inputs) does not fit
    that shape and is deliberately not here in P1; it needs a separate ``derive(inputs)``
    seam whose items carry ``method="synthesized"`` and ``derived_from`` set to their input
    refs (the ``Provenance.derived_from`` field is already in place). That arrives in P2.
    """

    name: str

    def fetch(self, target: str) -> list[Item]: ...


class Catalog:
    """A record of what has been gathered: one row per item, with its origin and fingerprint.

    The grown-up INDEX.json. Pure and deterministic; persists to JSON. Storage
    organization is a later phase; this is the minimal honest index.
    """

    def __init__(self) -> None:
        self._items: list[Item] = []

    def add(self, items: list[Item]) -> None:
        self._items.extend(items)

    def all(self) -> list[Item]:
        return list(self._items)

    def rows(self) -> list[dict]:
        return [
            {
                "kind": i.kind, "id": i.id, "title": i.title,
                "source": i.provenance.source, "ref": i.provenance.ref,
                "method": i.provenance.method, "sha256": i.provenance.sha256,
                "derived_from": list(i.provenance.derived_from), "chars": len(i.text),
            }
            for i in self._items
        ]

    def to_json(self) -> str:
        return json.dumps(self.rows(), indent=2, ensure_ascii=False)
