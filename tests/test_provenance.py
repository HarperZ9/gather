import sys

import pytest

from gather.item import make_item
from gather.provenance import (
    NullProvenanceProvider,
    ProvenanceProvider,
    SubprocessProvenanceProvider,
)
from gather.run import RunRecord, gather_run, verify_record


def _it(id, text):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source="web", ref=id, method="http-get", fetched_at=1.0)


class _FakeSource:
    name = "web"

    def __init__(self, items):
        self._items = items

    def fetch(self, target):
        return list(self._items)


def test_null_provenance_provider_makes_no_claim():
    assert NullProvenanceProvider().origin(_it("a", "x")) == {}


def test_subprocess_provider_parses_a_json_verdict():
    echo = [sys.executable, "-c", "import sys,json; sys.stdin.read(); sys.stdout.write(json.dumps({'origin':'verified'}))"]
    v = SubprocessProvenanceProvider(echo).origin(_it("a", "x"))
    assert v == {"origin": "verified"}


def test_subprocess_provider_reports_errors_instead_of_raising():
    failing = SubprocessProvenanceProvider([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert "error" in failing.origin(_it("a", "x"))           # non-zero exit -> error verdict, no raise
    not_json = SubprocessProvenanceProvider([sys.executable, "-c", "print('not json')"])
    assert "error" in not_json.origin(_it("a", "x"))          # unparseable output -> error verdict


def test_subprocess_provider_requires_a_command():
    with pytest.raises(ValueError):
        SubprocessProvenanceProvider([])


class _Fake(ProvenanceProvider):
    def origin(self, item):
        return {"verified": True, "for": item.id}


def test_run_records_and_seals_origin_verdicts():
    src = _FakeSource([_it("a", "alpha"), _it("b", "beta")])
    record, _ = gather_run([(src, "t")], clock=lambda: 9.0, provenance=_Fake())
    assert len(record.origins) == 2
    e = record.origins[0]
    assert e["origin"] == {"verified": True, "for": "a"}
    # keyed by the full receipt identity so a verdict joins back to exactly one digest receipt
    assert e["id"] == "a" and e["source"] == "web" and e["method"] == "http-get" and e["ref"] == "a"
    assert verify_record(record) is True                      # origins are folded into the seal


def test_no_provider_run_is_backward_compatible_with_pre_origins_records():
    # the seal must not include origins when none were made, so a record written before origins
    # existed (v1.0-1.3) still verifies, and the default run serializes with no origins key
    src = _FakeSource([_it("a", "alpha")])
    record, _ = gather_run([(src, "t")], clock=lambda: 9.0)  # no provenance
    d = record.to_dict()
    assert "origins" not in d                                 # exactly the pre-origins on-disk shape
    assert verify_record(RunRecord.from_dict(d)) is True      # a pre-origins record re-checks clean


def test_a_raising_provider_degrades_to_an_error_verdict_not_an_aborted_run():
    class Raising:
        def origin(self, item):
            raise RuntimeError("boom")

    src = _FakeSource([_it("a", "alpha")])
    record, _ = gather_run([(src, "t")], clock=lambda: 9.0, provenance=Raising())
    assert "error" in record.origins[0]["origin"]            # the run completed; the verdict is an error
    assert verify_record(record) is True


def test_oversized_verdict_is_refused():
    big = SubprocessProvenanceProvider(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.stdout.write('x' * 100000)"],
        max_output_bytes=1000,
    )
    v = big.origin(_it("a", "x"))
    assert "error" in v and "exceeded" in v["error"]


def test_origins_survive_the_record_round_trip():
    import json

    src = _FakeSource([_it("a", "alpha")])
    record, _ = gather_run([(src, "t")], clock=lambda: 9.0, provenance=_Fake())
    reloaded = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert reloaded == record and verify_record(reloaded) is True


def test_a_run_without_a_provider_has_no_origins():
    src = _FakeSource([_it("a", "alpha")])
    record, _ = gather_run([(src, "t")], clock=lambda: 9.0)
    assert record.origins == ()
