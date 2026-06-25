from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from gather.item import Item
from gather.scope import in_scope
from gather.store import CORRUPT, MISSING


class CorpusLike(Protocol):
    """What recall needs from a store: stream rows, reconstruct an item from a row."""

    def rows(self) -> Iterator[dict]: ...
    def load_item(self, row: dict) -> Item: ...


@dataclass(frozen=True, slots=True)
class Query:
    """A query over a stored corpus. Empty fields match everything.

    ``terms`` are scope keywords matched as case-insensitive substrings against an item's title
    and body (so ``art`` also matches ``cartesian``; this requires reading the body).
    ``sources``, ``kinds``, and ``methods`` are exact-match filters answered from the catalog row
    alone (cheap, no body read). Within one filter the match is ANY of its values (OR); across
    filters all must match (AND). So ``Query(sources=("web","arxiv"), kinds=("paper",))`` means
    "(web OR arxiv) AND paper".
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


def recall_audited(corpus: CorpusLike, query: Query, *, limit: int | None = None) -> tuple[list[Item], list[dict]]:
    """Recall matching items AND report what was skipped. Returns ``(items, skipped)``.

    An accountable query returns only items whose body is present and re-verifies against its
    receipt: a row whose body is gone is skipped as MISSING, and a row whose body no longer hashes
    to its receipt is skipped as CORRUPT, rather than crashing or handing back a tampered body.
    ``skipped`` carries one ``{id, sha256, status}`` per such row, so corruption is surfaced, not
    hidden. Streams the catalog; metadata filters are answered from the row before any body is
    read; integrity is checked only on items that pass the term filter (the ones to be returned).
    """
    if limit is not None and limit <= 0:
        return [], []
    kept: list[Item] = []
    skipped: list[dict] = []
    for row in corpus.rows():
        if not _row_matches(row, query):
            continue
        try:
            item = corpus.load_item(row)
        except FileNotFoundError:
            skipped.append({"id": row.get("id", ""), "sha256": row.get("sha256", ""), "status": MISSING})
            continue
        except ValueError:  # a non-hex / malformed sha is tampering, not absence (agrees with verify())
            skipped.append({"id": row.get("id", ""), "sha256": row.get("sha256", ""), "status": CORRUPT})
            continue
        if query.terms and not in_scope(item, query.terms):
            continue
        if not item.verify():
            skipped.append({"id": row.get("id", ""), "sha256": row.get("sha256", ""), "status": CORRUPT})
            continue
        kept.append(item)
        if limit is not None and len(kept) >= limit:
            break
    return kept, skipped


def recall(corpus: CorpusLike, query: Query, *, limit: int | None = None) -> list[Item]:
    """The items matching a query, reconstructed and re-verified (missing/corrupt bodies skipped).

    Order-preserving (catalog order), streams the catalog, and stops early once ``limit`` matches
    are found (``limit <= 0`` returns nothing). For the skipped-on-integrity report use
    ``recall_audited``.
    """
    return recall_audited(corpus, query, limit=limit)[0]
