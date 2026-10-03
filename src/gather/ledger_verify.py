"""Recompute a filter ledger from the ledger and its input file. Pure apart from reading files.

``verify_ledger`` returns a list of problems; an empty list means every count recomputes.
Checks, in order: the schema; the input count and digest against the input items; each dropped
row's index, id and hash against the input item at that index; one row per index; kept plus
dropped equals the input; the counts by reason equal the rows; and, when the only filter is the
built-in scope filter, a fresh run of that filter yields the same rows.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from gather.filter_ledger import (
    LEDGER_SCHEMA,
    SCOPE_REASON,
    input_digest,
    read_input,
    scope_with_ledger,
)
from gather.item import Item


def _row_problems(rows: list, items: Sequence[Item]) -> list[str]:
    problems = []
    seen: set[int] = set()
    for r in rows:
        i = r.get("index")
        if not isinstance(i, int) or not 0 <= i < len(items):
            problems.append(f"row {r.get('id')!r}: index {i!r} is outside the input")
            continue
        if i in seen:
            problems.append(f"index {i} is dropped more than once")
        seen.add(i)
        it = items[i]
        if r.get("sha256") != it.provenance.sha256 or r.get("id") != it.id:
            problems.append(f"row at index {i} does not match the input item there")
        if not isinstance(r.get("reason"), str) or not r["reason"]:
            problems.append(f"row at index {i} has no reason code")
    return problems


def _count_problems(ledger: dict, items: Sequence[Item]) -> list[str]:
    rows = ledger.get("rows") or []
    problems = []
    if ledger.get("dropped") != len(rows):
        problems.append(f"dropped is {ledger.get('dropped')} but there are {len(rows)} rows")
    if ledger.get("kept", -1) + len(rows) != len(items):
        problems.append(f"kept {ledger.get('kept')} plus dropped {len(rows)} is not the input total {len(items)}")
    recount = Counter(r.get("reason") for r in rows)
    stated = {k: v for k, v in (ledger.get("by_reason") or {}).items() if v}
    if stated != dict(recount):
        problems.append(f"counts by reason {stated} do not match the rows {dict(recount)}")
    return problems


def _rerun_scope(ledger: dict, items: Sequence[Item]) -> list[str]:
    filters = ledger.get("filters") or []
    if len(filters) != 1 or filters[0].get("filter") != "scope" or filters[0].get("reason") != SCOPE_REASON:
        return []
    _, fresh = scope_with_ledger(items, filters[0].get("terms") or [])
    return [] if fresh["rows"] == ledger.get("rows") else ["a fresh run of the scope filter drops different items"]


def verify_ledger(ledger: dict, items: Sequence[Item]) -> list[str]:
    if ledger.get("schema") != LEDGER_SCHEMA:
        return [f"not a {LEDGER_SCHEMA} ledger"]
    problems = []
    stated = ledger.get("input") or {}
    if stated.get("count") != len(items):
        problems.append(f"the ledger names {stated.get('count')} input items; the input file holds {len(items)}")
    if stated.get("digest") != input_digest([i.provenance.sha256 for i in items]):
        problems.append("the input digest does not match the input file")
    problems += _row_problems(ledger.get("rows") or [], items)
    problems += _count_problems(ledger, items)
    if not problems:
        problems += _rerun_scope(ledger, items)
    return problems


def verify_files(ledger_path: str, input_path: str) -> list[str]:
    import json
    with open(ledger_path, encoding="utf-8") as f:
        ledger = json.load(f)
    return verify_ledger(ledger, read_input(input_path))
