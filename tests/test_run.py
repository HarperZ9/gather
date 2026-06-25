import dataclasses

from gather.derive import NullSynthesizer
from gather.item import make_item
from gather.run import RunRecord, gather_run, verify_record
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


def test_run_record_round_trips_through_json_and_still_verifies():
    # the seal must survive persistence: dict -> json -> dict -> from_dict -> verify
    import json

    src = FakeSource("web", [_it("a", "alpha"), _it("b", "beta")])
    record, _ = gather_run([(src, "t")], clock=_clock, synthesizer=NullSynthesizer())
    reloaded = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert reloaded == record               # full fidelity through JSON
    assert verify_record(reloaded) is True  # the persisted record re-checks


def test_persisted_run_record_is_re_checkable_from_the_corpus(tmp_path):
    src = FakeSource("web", [_it("a", "alpha")])
    store = Corpus(str(tmp_path), fsync=False)
    record, _ = gather_run([(src, "t")], clock=_clock, store=store)
    row = next(store.runs())
    assert verify_record(RunRecord.from_dict(row)) is True
    # a tampered persisted record is caught
    row["kept"] = 999
    assert verify_record(RunRecord.from_dict(row)) is False


def test_second_run_into_a_corpus_diverges_from_the_whole_corpus_digest(tmp_path):
    store = Corpus(str(tmp_path), fsync=False)
    r1, _ = gather_run([(FakeSource("web", [_it("a", "alpha")]), "t")], clock=_clock, store=store)
    assert store.digest().seal == r1.digest_seal          # first run: corpus == that run
    r2, _ = gather_run([(FakeSource("web", [_it("b", "beta")]), "t")], clock=_clock, store=store)
    assert store.digest().seal != r2.digest_seal          # corpus now covers both runs, not just r2
    assert r2.digest_seal != r1.digest_seal


def test_digested_count_reconciles_kept_and_synthesis():
    src = FakeSource("web", [_it("a", "alpha"), _it("b", "beta")])
    record, items = gather_run([(src, "t")], clock=_clock, synthesizer=NullSynthesizer())
    assert record.kept == 2 and record.synthesized is True
    assert record.digested == 3 == len(items)             # kept + the one synthesized item


def test_synth_item_admitted_on_input_provenance_even_if_out_of_scope():
    # a model synthesizer can emit text without the scope terms; it is still admitted, on the
    # provenance of its in-scope inputs (derived_from), not re-scoped on its own text
    class OffTopicModel:
        method = "synthesized"

        def synthesize(self, inputs, prompt):
            return "an inference mentioning none of the terms"

    src = FakeSource("web", [_it("a", "about tiling")])
    record, items = gather_run([(src, "t")], clock=_clock, scope=["tiling"],
                               synthesizer=OffTopicModel())
    syn = items[-1]
    assert syn.provenance.method == "synthesized"
    assert "tiling" not in syn.text                       # out of scope on its own text
    assert syn.provenance.derived_from == (items[0].provenance.sha256,)  # but tied to in-scope input
    assert record.digested == 2


def test_run_multiple_sources_collects_all():
    s1 = FakeSource("web", [_it("a", "alpha")])
    s2 = FakeSource("feed", [_it("b", "beta", source="feed")])
    record, items = gather_run([(s1, "t1"), (s2, "t2")], clock=_clock)
    assert record.gathered == 2 and record.kept == 2
    assert record.targets == (("web", "t1"), ("feed", "t2"))
    assert {i.id for i in items} == {"a", "b"}
