"""Filter ledgers: what a filter dropped, item by item, with one reason code each.

A filter that keeps some items and drops others makes a judgment a reader cannot see in the kept
set alone. ``apply_filters`` runs named filters in order; the first filter that rejects an item
gives its reason code, so every dropped item has exactly one. The ledger records the input
(count and a digest over the items' content hashes, in order), one row per dropped item (index,
id, content hash, reason), counts by reason, and the parameters of each filter.

``write_ledger`` saves the ledger and the input items beside it (``ledger.json`` and
``input.jsonl``), so a second person can recompute every count. ``verify_ledger`` does that
recomputation: it rebuilds the input digest, checks every row against the input, checks that
kept plus dropped equals the input and that the counts by reason match the rows, and, for the
built-in scope filter, runs the filter again and compares.

A ledger makes the filtering inspectable. It does not show that the filtering was fair, and a
reason code can still carry a judgment inside its label.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from gather.item import Item, make_item
from gather.scope import in_scope

LEDGER_SCHEMA = "gather.filter-ledger/1"
SCOPE_REASON = "out-of-scope"
DOES_NOT_PROVE = "that the filtering was fair; it makes the filtering inspectable"


@dataclass(frozen=True, slots=True)
class Filter:
    """One named filter: ``keep(item)`` returns True to keep; a drop is recorded as ``reason``."""

    reason: str
    keep: Callable[[Item], bool]
    params: dict[str, Any] = field(default_factory=dict)


def scope_filter(terms: Sequence[str]) -> Filter:
    term_list = [t for t in terms if t]
    return Filter(SCOPE_REASON, lambda it: in_scope(it, term_list), {"filter": "scope", "terms": term_list})


def input_digest(hashes: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


def apply_filters(items: Sequence[Item], filters: Sequence[Filter]) -> tuple[list[Item], dict]:
    """The kept items, in order, and the ledger of the dropped."""
    kept: list[Item] = []
    rows: list[dict] = []
    for index, it in enumerate(items):
        reason = next((f.reason for f in filters if not f.keep(it)), None)
        if reason is None:
            kept.append(it)
        else:
            rows.append({"index": index, "id": it.id, "sha256": it.provenance.sha256, "reason": reason})
    by_reason = {f.reason: sum(1 for r in rows if r["reason"] == f.reason) for f in filters}
    ledger = {
        "schema": LEDGER_SCHEMA,
        "filters": [{"reason": f.reason, **f.params} for f in filters],
        "input": {"count": len(items), "digest": input_digest([i.provenance.sha256 for i in items])},
        "kept": len(kept), "dropped": len(rows), "by_reason": by_reason, "rows": rows,
        "does_not_prove": DOES_NOT_PROVE,
    }
    return kept, ledger


def scope_with_ledger(items: Sequence[Item], terms: Sequence[str]) -> tuple[list[Item], dict]:
    """The scope filter with its ledger. No terms keeps everything and drops nothing."""
    return apply_filters(items, [scope_filter(terms)] if [t for t in terms if t] else [])


def _item_row(it: Item) -> dict:
    p = it.provenance
    return {"kind": it.kind, "id": it.id, "title": it.title, "text": it.text, "source": p.source,
            "ref": p.ref, "method": p.method, "fetched_at": p.fetched_at, "sha256": p.sha256}


def write_ledger(directory: str, ledger: dict, items: Sequence[Item]) -> dict[str, str]:
    """Write ``ledger.json`` and ``input.jsonl`` into ``directory`` (created if absent)."""
    os.makedirs(directory, exist_ok=True)
    paths = {"ledger": os.path.join(directory, "ledger.json"), "input": os.path.join(directory, "input.jsonl")}
    with open(paths["input"], "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(_item_row(it), ensure_ascii=False, sort_keys=True) + "\n")
    with open(paths["ledger"], "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
    return paths


def read_input(path: str) -> list[Item]:
    """Items from an ``input.jsonl``. A row whose text no longer matches its hash is an error."""
    items = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            r = json.loads(line)
            it = make_item(kind=r["kind"], id=r["id"], title=r["title"], text=r["text"], source=r["source"],
                           ref=r["ref"], method=r["method"], fetched_at=r["fetched_at"])
            if it.provenance.sha256 != r["sha256"]:
                raise ValueError(f"input line {n}: text does not match its sha256")
            items.append(it)
    return items
