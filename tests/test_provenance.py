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
    assert record.origins[0]["origin"] == {"verified": True, "for": "a"}
    assert verify_record(record) is True                      # origins are folded into the seal


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
