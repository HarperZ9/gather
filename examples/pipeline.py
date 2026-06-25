"""Gather: the whole organ in one offline run (no install, no network, nothing downloaded).

Runs a witnessed gather session over an in-memory source, persists it to a content-addressed
corpus, re-verifies every stored body against its receipt, recalls a scoped subset, and shows the
run record re-checking from disk. Everything here is deterministic.

Run:  python examples/pipeline.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from gather.derive import NullSynthesizer
from gather.item import make_item
from gather.recall import Query, recall
from gather.run import RunRecord, gather_run, verify_record
from gather.store import Corpus


class MemorySource:
    """A stand-in adapter so the example needs no network: it just returns prepared items."""

    name = "web"

    def __init__(self, items):
        self._items = items

    def fetch(self, target):
        return list(self._items)


def main() -> None:
    items = [
        make_item(kind="webpage", id="p1", title="Aperiodic monotiles",
                  text="a single shape that tiles the plane without ever repeating",
                  source="web", ref="https://example/p1", method="http-get", fetched_at=1.0),
        make_item(kind="webpage", id="p2", title="Sourdough",
                  text="a loaf, unrelated to the research", source="web",
                  ref="https://example/p2", method="http-get", fetched_at=1.0),
    ]
    src = MemorySource(items)

    with tempfile.TemporaryDirectory() as d:
        store = Corpus(d, fsync=False)
        # one witnessed run: fetch -> scope to the work -> compile a summary -> digest -> store
        record, kept = gather_run(
            [(src, "research")], clock=lambda: 100.0, scope=["tile", "monotile"],
            synthesizer=NullSynthesizer(), synth_prompt="research summary", store=store,
        )
        print(f"run: gathered {record.gathered}, kept {record.kept}, dropped {record.dropped}, "
              f"+synthesis={record.synthesized}, digested {record.digested}")
        print(f"     digest seal {record.digest_seal[:12]}...  record seal {record.seal[:12]}...")
        print(f"     record re-checks: {verify_record(record)}")
        print()

        # the stored corpus re-verifies every body against its receipt
        statuses = {r["status"] for r in store.verify()}
        print(f"corpus verify: {len(list(store.rows()))} items, statuses {statuses}")

        # recall a scoped, re-verified subset for a downstream organ
        found = recall(store, Query(terms=["monotile"]))
        print(f"recall 'monotile': {[i.id for i in found]} (each re-verifies: {all(i.verify() for i in found)})")
        print()

        # the run record is re-checkable from disk, not just in memory
        row = next(store.runs())
        print(f"run history on disk re-checks: {verify_record(RunRecord.from_dict(row))}")


if __name__ == "__main__":
    main()
