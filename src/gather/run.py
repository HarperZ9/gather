from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from gather.derive import Synthesizer, synthesize_item
from gather.digest import digest
from gather.item import Item
from gather.scope import filter_scope
from gather.source import Source

# The ScopeProvider seam: a callable that keeps the in-scope items and counts the dropped.
# The default is the deterministic keyword filter; a model-based scope plugs in here, the
# peer-composition way, without the run importing it.
ScopeFilter = Callable[[list[Item], Sequence[str]], tuple[list[Item], int]]

Job = tuple[Source, str]  # a source to run and the target to fetch


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A witnessed, re-checkable record of one gather session.

    It does not hold the items; it holds what happened (when, which targets, the scope, the
    counts, whether a synthesis was added) and the digest seal that fingerprints the items. Its
    own ``seal`` is a hash over those fields, so a reader can confirm the record was not altered,
    and the ``digest_seal`` lets them confirm the items. Together the run is re-checkable.
    """

    started_at: float
    targets: tuple[tuple[str, str], ...]
    scope: tuple[str, ...]
    gathered: int
    kept: int
    dropped: int
    synthesized: bool
    digest_seal: str
    stored: dict | None
    seal: str

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at, "targets": [list(t) for t in self.targets],
            "scope": list(self.scope), "gathered": self.gathered, "kept": self.kept,
            "dropped": self.dropped, "synthesized": self.synthesized,
            "digest_seal": self.digest_seal, "stored": self.stored, "seal": self.seal,
        }


def _record_fields(
    started_at: float, targets: tuple[tuple[str, str], ...], scope: tuple[str, ...],
    gathered: int, kept: int, dropped: int, synthesized: bool, digest_seal: str, stored: dict | None,
) -> dict:
    return {
        "started_at": started_at, "targets": [list(t) for t in targets], "scope": list(scope),
        "gathered": gathered, "kept": kept, "dropped": dropped, "synthesized": synthesized,
        "digest_seal": digest_seal, "stored": stored,
    }


def _seal_record(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def gather_run(
    jobs: list[Job],
    *,
    clock: Callable[[], float] = time.time,
    scope: Sequence[str] = (),
    scope_filter: ScopeFilter | None = None,
    synthesizer: Synthesizer | None = None,
    synth_prompt: str = "",
    synth_ref: str = "synthesis",
    store=None,
) -> tuple[RunRecord, list[Item]]:
    """Orchestrate one gather session and return its witnessed record and the kept items.

    The flow: fetch each (source, target) job, collect the items, scope-filter them, optionally
    fold them into one synthesized item through the Synthesizer seam, digest the result, and
    optionally persist it (and the record) to a corpus. The clock is injected, so given the same
    fetched items the record is deterministic and replayable. Composition seams default to Null
    (keyword scope, no synthesis) so the run stands alone, and a model-based scope or synthesizer
    plugs in without the run importing it.
    """
    started = float(clock())
    scope = tuple(scope)
    all_items: list[Item] = []
    targets: list[tuple[str, str]] = []
    for source, target in jobs:
        all_items.extend(source.fetch(target))
        targets.append((source.name, target))

    sfilter = scope_filter or filter_scope
    kept, dropped = sfilter(all_items, scope)

    final = list(kept)
    synthesized = False
    if synthesizer is not None and kept:
        final.append(synthesize_item(synthesizer, kept, synth_prompt, fetched_at=started, ref=synth_ref))
        synthesized = True

    seal = digest(final).seal
    stored = store.add(final) if store is not None else None

    targets_t = tuple(targets)
    fields = _record_fields(started, targets_t, scope, len(all_items), len(kept), dropped, synthesized, seal, stored)
    record = RunRecord(
        started_at=started, targets=targets_t, scope=scope, gathered=len(all_items),
        kept=len(kept), dropped=dropped, synthesized=synthesized, digest_seal=seal,
        stored=stored, seal=_seal_record(fields),
    )
    if store is not None:
        store.add_record(record.to_dict())
    return record, final


def verify_record(record: RunRecord) -> bool:
    """Recompute the record's seal from its fields and confirm it matches (the record was not altered)."""
    fields = _record_fields(
        record.started_at, record.targets, record.scope, record.gathered,
        record.kept, record.dropped, record.synthesized, record.digest_seal, record.stored,
    )
    return _seal_record(fields) == record.seal
