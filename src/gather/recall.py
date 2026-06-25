from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from gather.item import Item
from gather.scope import in_scope


class CorpusLike(Protocol):
    """What recall needs from a store: stream rows, reconstruct an item from a row."""

    def rows(self) -> Iterator[dict]: ...
    def load_item(self, row: dict) -> Item: ...


@dataclass(frozen=True, slots=True)
class Query:
    """A query over a stored corpus. Empty fields match everything.

    ``terms`` are scope keywords matched against an item's title and body (so they require reading
    the body); ``sources``, ``kinds``, and ``methods`` are exact-match filters answered from the
    catalog row alone (cheap, no body read). All given filters must match (AND).
    """

    terms: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()


def _row_matches(row: dict, q: Query) -> bool:
    return (
        (not q.sources or row.get("source") in q.sources)
        and (not q.kinds or row.get("kind") in q.kinds)
        and (not q.methods or row.get("method") in q.methods)
    )


def recall(corpus: CorpusLike, query: Query, *, limit: int | None = None) -> list[Item]:
    """Return the corpus items matching a query, reconstructed (and so re-verifiable).

    Streams the catalog: the cheap metadata filters (source/kind/method) are answered from the row
    before a body is read, and only survivors have their body loaded to check ``terms`` and to be
    returned. Order-preserving; stops early once ``limit`` matches are found.
    """
    out: list[Item] = []
    for row in corpus.rows():
        if not _row_matches(row, query):
            continue
        item = corpus.load_item(row)
        if query.terms and not in_scope(item, query.terms):
            continue
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out
