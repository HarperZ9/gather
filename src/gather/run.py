from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from gather.derive import Synthesizer, synthesize_item
from gather.digest import digest
from gather.item import Item
from gather.provenance import ProvenanceProvider
from gather.scope import filter_scope
from gather.source import Source

# The ScopeProvider seam: a callable that keeps the in-scope items and counts the dropped.
# The default is the deterministic keyword filter; a model-based scope plugs in here, the
# peer-composition way, without the run importing it.
ScopeFilter = Callable[[list[Item], Sequence[str]], tuple[list[Item], int]]

Job = tuple[Source, str]  # a source to run and the target to fetch


class StoreLike(Protocol):
    """The store seam: anywhere a run can persist its items and its record (gather.store.Corpus)."""

    def add(self, items: list[Item]) -> dict[str, int]: ...
    def add_record(self, record: dict) -> None: ...


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
    gathered: int       # items fetched across all jobs
    kept: int           # in-scope items (before any synthesis)
    dropped: int        # items filtered out of scope
    synthesized: bool   # whether one synthesized item was appended
    digested: int       # items folded into the digest and stored: kept plus the synthesis if any
    origins: tuple[dict, ...]  # per-item external origin verdicts (empty unless a ProvenanceProvider ran)
    digest_seal: str
    stored: dict | None
    seal: str

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at, "targets": [list(t) for t in self.targets],
            "scope": list(self.scope), "gathered": self.gathered, "kept": self.kept,
            "dropped": self.dropped, "synthesized": self.synthesized, "digested": self.digested,
            "origins": list(self.origins),
            "digest_seal": self.digest_seal, "stored": self.stored, "seal": self.seal,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RunRecord:
        """Reconstruct a RunRecord from its dict form (e.g. a row of the corpus run history), so
        a persisted record can be re-checked with verify_record. Raises a clear ValueError on a
        malformed row (the run history can be hand-edited or corrupted), not a bare KeyError."""
        try:
            return cls(
                started_at=d["started_at"],
                targets=tuple(tuple(t) for t in d["targets"]),
                scope=tuple(d["scope"]),
                gathered=d["gathered"], kept=d["kept"], dropped=d["dropped"],
                synthesized=d["synthesized"], digested=d["digested"],
                origins=tuple(d.get("origins") or ()),
                digest_seal=d["digest_seal"], stored=d["stored"], seal=d["seal"],
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed run record: {exc}") from exc


def _record_fields(
    started_at: float, targets: tuple[tuple[str, str], ...], scope: tuple[str, ...],
    gathered: int, kept: int, dropped: int, synthesized: bool, digested: int,
    origins: tuple[dict, ...], digest_seal: str, stored: dict | None,
) -> dict:
    return {
        "started_at": started_at, "targets": [list(t) for t in targets], "scope": list(scope),
        "gathered": gathered, "kept": kept, "dropped": dropped, "synthesized": synthesized,
        "digested": digested, "origins": list(origins), "digest_seal": digest_seal, "stored": stored,
    }


def _seal_record(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _dedup_by_receipt(items: list[Item]) -> list[Item]:
    """Drop items with a duplicate receipt identity (the corpus's dedup key), preserving order."""
    seen: set[tuple] = set()
    out: list[Item] = []
    for it in items:
        p = it.provenance
        key = (it.kind, it.id, it.title, p.source, p.ref, p.method, p.sha256, p.derived_from)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def gather_run(
    jobs: list[Job],
    *,
    clock: Callable[[], float] = time.time,
    scope: Sequence[str] = (),
    scope_filter: ScopeFilter | None = None,
    synthesizer: Synthesizer | None = None,
    synth_prompt: str = "",
    synth_ref: str = "synthesis",
    store: StoreLike | None = None,
    provenance: ProvenanceProvider | None = None,
) -> tuple[RunRecord, list[Item]]:
    """Orchestrate one gather session and return its witnessed record and the digested items.

    The flow: fetch each (source, target) job, collect the items, scope-filter them, optionally
    fold them into one synthesized item through the Synthesizer seam, digest the result, and
    optionally persist it (and the record) to a corpus. The clock is injected, so given the same
    fetched items the record is deterministic and replayable. Composition seams default to Null
    (keyword scope, no synthesis) so the run stands alone, and a model-based scope or synthesizer
    plugs in without the run importing it.

    Two notes on what the record means. The synthesized item is appended after scope filtering and
    is NOT re-scoped on its own text: it is admitted on the provenance of its in-scope inputs
    (which ``derived_from`` records), so with a model synthesizer the digested set can hold an item
    that does not itself contain the scope terms. And persistence is two-phase: the items are
    stored, then the record is appended to the run history; so a crash between them can leave items
    stored without a record (the items still verify; only the run's witness is missing), never the
    reverse. ``record.digest_seal`` fingerprints THIS run's digested items; a corpus's own digest
    fingerprints the whole corpus, so the two coincide only for the first run into a fresh corpus.
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

    # dedup by receipt identity, the same key the corpus uses, so the run's digest seal equals the
    # seal of what the corpus stores (a source that lists the same item twice would otherwise diverge)
    final = _dedup_by_receipt(final)

    # compose an external origin verdict per item, if a provenance organ is wired in (Null does none)
    origins: tuple[dict, ...] = ()
    if provenance is not None:
        origins = tuple(
            {"id": it.id, "sha256": it.provenance.sha256, "origin": provenance.origin(it)}
            for it in final
        )

    seal = digest(final).seal
    stored = store.add(final) if store is not None else None

    targets_t = tuple(targets)
    fields = _record_fields(started, targets_t, scope, len(all_items), len(kept), dropped,
                            synthesized, len(final), origins, seal, stored)
    record = RunRecord(
        started_at=started, targets=targets_t, scope=scope, gathered=len(all_items),
        kept=len(kept), dropped=dropped, synthesized=synthesized, digested=len(final),
        origins=origins, digest_seal=seal, stored=stored, seal=_seal_record(fields),
    )
    if store is not None:
        store.add_record(record.to_dict())
    return record, final


def verify_record(record: RunRecord) -> bool:
    """Recompute the record's seal from its fields and confirm it matches (the record was not
    altered). Works on a record reconstructed from disk via RunRecord.from_dict too."""
    fields = _record_fields(
        record.started_at, record.targets, record.scope, record.gathered, record.kept,
        record.dropped, record.synthesized, record.digested, record.origins,
        record.digest_seal, record.stored,
    )
    return _seal_record(fields) == record.seal
