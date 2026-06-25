import dataclasses

from gather.derive import NullSynthesizer
from gather.item import make_item
from gather.run import gather_run, verify_record
from gather.store import Corpus


class FakeSource:
    """An in-memory source so the run is tested deterministically, with no network."""

    def __init__(self, name, items):
        self.name = name
        self._items = items

    def fetch(self, target):
        return list(self._items)


def _it(id, text, source="web"):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source=source, ref=id, method="http-get", fetched_at=1.0)


def _clock():
    return 100.0


def test_run_gathers_scopes_digests_and_witnesses():
    src = FakeSource("web", [_it("a", "about tiling"), _it("b", "about groups")])
    record, items = gather_run([(src, "t")], clock=_clock, scope=["tiling"])
    assert record.gathered == 2 and record.kept == 1 and record.dropped == 1
    assert record.started_at == 100.0
    assert len(record.digest_seal) == 64
    assert verify_record(record) is True          # the record's own seal checks out
    assert [i.id for i in items] == ["a"]


def test_run_record_seal_detects_tampering():
    src = FakeSource("web", [_it("a", "x")])
    record, _ = gather_run([(src, "t")], clock=_clock)
    assert verify_record(record) is True
    tampered = dataclasses.replace(record, kept=999)
    assert verify_record(tampered) is False        # altering a counted field breaks the seal


def test_run_with_synthesizer_appends_one_compiled_item():
    src = FakeSource("web", [_it("a", "alpha"), _it("b", "beta")])
    record, items = gather_run([(src, "t")], clock=_clock, synthesizer=NullSynthesizer(), synth_prompt="sum")
    assert record.synthesized is True
    syn = items[-1]
    assert syn.provenance.method == "compiled"     # the Null default never claims a synthesis
    assert syn.provenance.derived_from == (items[0].provenance.sha256, items[1].provenance.sha256)
    assert verify_record(record) is True


def test_run_persists_items_and_record_to_a_corpus(tmp_path):
    src = FakeSource("web", [_it("a", "alpha"), _it("b", "beta")])
    store = Corpus(str(tmp_path), fsync=False)
    record, _ = gather_run([(src, "t")], clock=_clock, store=store)
    assert record.stored == {"added": 2, "deduped": 0, "total": 2}
    history = list(store.runs())
    assert len(history) == 1 and history[0]["seal"] == record.seal      # the run is in the durable history
    assert {r["id"] for r in store.rows()} == {"a", "b"}                # the items are in the corpus
    assert store.digest().seal == record.digest_seal                    # corpus seals to the run's digest


def test_run_multiple_sources_collects_all():
    s1 = FakeSource("web", [_it("a", "alpha")])
    s2 = FakeSource("feed", [_it("b", "beta", source="feed")])
    record, items = gather_run([(s1, "t1"), (s2, "t2")], clock=_clock)
    assert record.gathered == 2 and record.kept == 2
    assert record.targets == (("web", "t1"), ("feed", "t2"))
    assert {i.id for i in items} == {"a", "b"}
