import dataclasses
import json
import os

from gather.digest import digest_of_receipts, verify_digest
from gather.item import content_hash, make_item
from gather.store import Corpus


def _it(id, text):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source="web", ref=id, method="http-get", fetched_at=1.0)


def _row(id, text, availability=None):
    row = {"kind": "document", "id": id, "title": f"T{id}", "source": "web",
           "ref": id, "method": "http-get", "sha256": content_hash(text)}
    if availability is not None:
        row["availability"] = availability
    return row


def _rung(status, checked_at, sha256):
    return {"status": status, "checked_at": checked_at, "sha256": sha256}


# --- the seal covers the rung (a rung sealed at witnessing cannot be edited undetected) ---


def test_a_rung_is_carried_into_the_sealed_receipts():
    rung = _rung("AVAILABLE", 2.0, content_hash("alpha"))
    d = digest_of_receipts([_row("a", "alpha", availability=rung)])
    assert d.receipts[0]["availability"] == rung
    assert verify_digest(d) is True


def test_editing_a_sealed_availability_rung_breaks_the_seal():
    rung = _rung("AVAILABLE", 2.0, content_hash("alpha"))
    d = digest_of_receipts([_row("a", "alpha", availability=rung)])
    for edit in ({"status": "UNAVAILABLE"},                 # flip the status
                 {"checked_at": 3.0},                       # backdate/postdate the check
                 {"sha256": content_hash("tampered")}):     # rebind the claim to other content
        edited = dataclasses.replace(
            d, receipts=({**d.receipts[0], "availability": {**rung, **edit}},))
        assert verify_digest(edited) is False, f"edit {edit} must break the seal"


def test_adding_or_removing_a_rung_after_sealing_breaks_the_seal():
    rung = _rung("AVAILABLE", 2.0, content_hash("alpha"))
    sealed_with = digest_of_receipts([_row("a", "alpha", availability=rung)])
    stripped = dataclasses.replace(
        sealed_with, receipts=({k: v for k, v in sealed_with.receipts[0].items()
                                if k != "availability"},))
    assert verify_digest(stripped) is False   # removing the witnessed rung is detected
    sealed_without = digest_of_receipts([_row("a", "alpha")])
    grafted = dataclasses.replace(
        sealed_without, receipts=({**sealed_without.receipts[0], "availability": rung},))
    assert verify_digest(grafted) is False    # grafting a rung onto a legacy record is detected


def test_sealing_rejects_a_malformed_rung():
    import pytest
    for bad in ("yes", {}, _rung("AVAILABLE", "soon", content_hash("x")),
                _rung("AVAILABLE", 2.0, "nothex")):
        with pytest.raises(ValueError, match="availability rung"):
            digest_of_receipts([_row("a", "alpha", availability=bad)])


# --- typed re-verification outcomes (the claim is gated on the hash binding, not the string) ---


def test_available_claim_with_a_mismatched_hash_is_rejected_as_changed():
    from gather.availability import AVAILABLE, CHANGED, assess_availability
    row = _row("a", "alpha", availability=_rung("AVAILABLE", 2.0, content_hash("tampered")))
    outcome = assess_availability(row)
    assert outcome == CHANGED
    assert outcome != AVAILABLE   # an author-written "AVAILABLE" never survives a hash mismatch


def test_matching_hash_binding_assesses_available():
    from gather.availability import AVAILABLE, assess_availability
    row = _row("a", "alpha", availability=_rung("AVAILABLE", 2.0, content_hash("alpha")))
    assert assess_availability(row) == AVAILABLE


def test_unavailable_rung_assesses_unavailable():
    from gather.availability import UNAVAILABLE, assess_availability
    row = _row("a", "alpha", availability=_rung("UNAVAILABLE", 2.0, ""))
    assert assess_availability(row) == UNAVAILABLE


def test_legacy_receipts_still_verify_but_report_unwitnessed_never_available():
    from gather.availability import UNWITNESSED, assess_availability
    items = [_it("a", "alpha"), _it("b", "beta")]
    from gather.digest import digest
    d = digest(items)                          # a pre-rung digest: no availability anywhere
    assert verify_digest(d) is True            # backward compatible: the old seal still verifies
    assert all(assess_availability(r) == UNWITNESSED for r in d.receipts)


def test_a_malformed_rung_never_reports_available():
    from gather.availability import AVAILABLE, UNWITNESSED, assess_availability
    sha = content_hash("alpha")
    for bad in ("yes", {}, _rung("PROBABLY", 2.0, sha), _rung("AVAILABLE", 2.0, ""),
                _rung("AVAILABLE", "soon", sha), _rung("UNAVAILABLE", 2.0, sha)):
        outcome = assess_availability(_row("a", "alpha", availability=bad))
        assert outcome == UNWITNESSED
        assert outcome != AVAILABLE


def test_rung_builder_rejects_inconsistent_claims():
    import pytest

    from gather.availability import AVAILABLE, UNAVAILABLE, availability_rung
    ok = availability_rung(status=AVAILABLE, checked_at=2.0, sha256=content_hash("x"))
    assert ok == {"status": AVAILABLE, "checked_at": 2.0, "sha256": content_hash("x")}
    with pytest.raises(ValueError):
        availability_rung(status="PROBABLY", checked_at=2.0, sha256="")
    with pytest.raises(ValueError):
        availability_rung(status=AVAILABLE, checked_at=2.0, sha256="")   # available binds a hash
    with pytest.raises(ValueError):
        availability_rung(status=UNAVAILABLE, checked_at=2.0, sha256=content_hash("x"))


# --- witnessing a corpus: the check distinguishes unavailable from changed ---


def test_witness_distinguishes_available_unavailable_and_changed(tmp_path):
    from gather.availability import (
        AVAILABLE,
        CHANGED,
        UNAVAILABLE,
        assess_availability,
        stored_probe,
        witness_availability,
    )
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha"), _it("b", "beta"), _it("d", "delta")])
    os.remove(c._object_path(content_hash("beta")))          # source no longer available
    with open(c._object_path(content_hash("delta")), "w", encoding="utf-8") as f:
        f.write("rewritten")                                  # source content changed

    d = witness_availability(list(c.rows()), stored_probe(c), clock=lambda: 9.0)
    assert verify_digest(d) is True
    by_id = {r["id"]: assess_availability(r) for r in d.receipts}
    assert by_id == {"a": AVAILABLE, "b": UNAVAILABLE, "d": CHANGED}
    rungs = {r["id"]: r["availability"] for r in d.receipts}
    assert rungs["a"]["checked_at"] == 9.0
    assert rungs["a"]["sha256"] == content_hash("alpha")     # the binding is the observed hash
    assert rungs["b"]["sha256"] == ""                        # nothing observed, nothing claimed
    assert rungs["d"]["status"] == "AVAILABLE"               # the source answered ...
    assert rungs["d"]["sha256"] == content_hash("rewritten")  # ... with different content


def test_a_probe_that_raises_is_recorded_as_unavailable():
    from gather.availability import UNAVAILABLE, check_receipts

    def probe(_row):
        raise OSError("network down")

    checked = check_receipts([_row("a", "alpha")], probe, clock=lambda: 9.0)
    assert checked[0]["availability"] == _rung(UNAVAILABLE, 9.0, "")


# --- the CLI surface ---


def test_corpus_availability_command_gates_on_typed_outcomes(tmp_path, capsys):
    from gather.cli import main
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha"), _it("b", "beta"), _it("d", "delta")])

    assert main(["corpus", "availability", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {o["availability"] for o in out["outcomes"]} == {"AVAILABLE"}
    assert len(out["digest"]["seal"]) == 64

    os.remove(c._object_path(content_hash("beta")))
    with open(c._object_path(content_hash("delta")), "w", encoding="utf-8") as f:
        f.write("rewritten")
    assert main(["corpus", "availability", str(tmp_path), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    by_id = {o["id"]: o["availability"] for o in out["outcomes"]}
    assert by_id == {"a": "AVAILABLE", "b": "UNAVAILABLE", "d": "CHANGED"}
