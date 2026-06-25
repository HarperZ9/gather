import os

from gather.digest import digest, verify_digest
from gather.item import content_hash, make_item
from gather.store import CORRUPT, MATCH, MISSING, Corpus


def _it(id, text, source="web"):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source=source, ref=id, method="http-get", fetched_at=1.0)


def test_add_stores_objects_and_catalog_rows(tmp_path):
    c = Corpus(str(tmp_path))
    res = c.add([_it("a", "alpha"), _it("b", "beta")])
    assert res == {"added": 2, "deduped": 0, "total": 2}
    assert len(list(c.rows())) == 2
    assert os.path.exists(c._object_path(content_hash("alpha")))


def test_identical_content_is_deduped(tmp_path):
    c = Corpus(str(tmp_path))
    c.add([_it("a", "same")])
    res = c.add([_it("b", "same")])  # different id, identical body
    assert res == {"added": 0, "deduped": 1, "total": 1}
    assert len(list(c.rows())) == 1  # the body is stored once, first receipt kept


def test_round_trip_reconstructs_verifiable_items(tmp_path):
    c = Corpus(str(tmp_path))
    c.add([_it("a", "alpha"), _it("b", "beta")])
    loaded = [c.load_item(r) for r in c.rows()]
    assert [i.id for i in loaded] == ["a", "b"]
    assert all(i.verify() for i in loaded)            # the receipt still matches the stored body
    assert loaded[0].text == "alpha"


def test_verify_reports_match_missing_and_corrupt(tmp_path):
    c = Corpus(str(tmp_path))
    c.add([_it("a", "alpha"), _it("b", "beta"), _it("d", "delta")])

    # intact: all MATCH
    assert {r["status"] for r in c.verify()} == {MATCH}

    # corrupt one object in place
    pa = c._object_path(content_hash("alpha"))
    with open(pa, "w", encoding="utf-8") as f:
        f.write("tampered")
    # remove another object entirely
    os.remove(c._object_path(content_hash("beta")))

    by_id = {r["id"]: r["status"] for r in c.verify()}
    assert by_id["a"] == CORRUPT
    assert by_id["b"] == MISSING
    assert by_id["d"] == MATCH


def test_corpus_digest_matches_a_direct_digest(tmp_path):
    items = [_it("a", "alpha"), _it("b", "beta")]
    c = Corpus(str(tmp_path))
    c.add(items)
    d = c.digest()
    assert verify_digest(d) is True
    assert d.seal == digest(items).seal   # the stored corpus seals identically to the live items


def test_rows_on_empty_corpus_is_empty(tmp_path):
    assert list(Corpus(str(tmp_path / "fresh")).rows()) == []
