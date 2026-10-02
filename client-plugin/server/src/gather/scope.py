from __future__ import annotations

from collections.abc import Iterable

from gather.item import Item


def in_scope(item: Item, terms: Iterable[str]) -> bool:
    """True if the item's title or text mentions any scope term (case-insensitive).

    The scope-to-telos discipline: keep what serves the theses, drop the rest. A
    deterministic keyword gate; the terms come from the theses this gather serves.
    No terms means no filtering: everything is in scope.
    """
    lowered = [t.lower() for t in terms]
    if not lowered:
        return True
    hay = (item.title + "\n" + item.text).lower()
    return any(t in hay for t in lowered)


def filter_scope(items: list[Item], terms: Iterable[str]) -> tuple[list[Item], int]:
    """Return ``(kept items, dropped count)``. Deterministic and order-preserving."""
    term_list = list(terms)
    kept = [i for i in items if in_scope(i, term_list)]
    return kept, len(items) - len(kept)
