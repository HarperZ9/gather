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


def test_distinct_items_sharing_a_body_keep_both_receipts(tmp_path):
    # different provenance (id), identical text: BOTH receipts are kept, the body stored once
    c = Corpus(str(tmp_path))
    c.add([_it("a", "same")])
    res = c.add([_it("b", "same")])
    assert res == {"added": 1, "deduped": 0, "total": 1}   # the new receipt is added, not dropped
    assert {r["id"] for r in c.rows()} == {"a", "b"}        # no provenance lost
    assert len(os.listdir(os.path.join(str(tmp_path), "objects"))) == 1  # one shard: body stored once


def test_re_adding_an_identical_receipt_is_deduped(tmp_path):
    c = Corpus(str(tmp_path))
    c.add([_it("a", "alpha")])
    res = c.add([_it("a", "alpha")])  # same receipt entirely: a true no-op
    assert res == {"added": 0, "deduped": 1, "total": 1}
    assert len(list(c.rows())) == 1


def test_meta_round_trips_through_json(tmp_path):
    c = Corpus(str(tmp_path))
    it = make_item(kind="document", id="m", title="M", text="body", source="web", ref="m",
                   method="http-get", fetched_at=1.0, meta={"author": "x", "tags": ["a", "b"], "n": 3})
    c.add([it])
    back = c.load_item(next(c.rows()))
    assert back.meta == {"author": "x", "tags": ["a", "b"], "n": 3}
    assert back.verify()


def test_a_tampered_sha_in_the_catalog_cannot_traverse_out(tmp_path):
    # a hand-edited catalog sha must not drive a path-traversal read
    import pytest
    c = Corpus(str(tmp_path))
    with pytest.raises(ValueError):
        c.read_text("../../../../etc/passwd")
    with pytest.raises(ValueError):
        c.read_text("nothex" * 10)


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


def test_corpus_digest_matches_across_multiple_adds_and_shared_bodies(tmp_path):
    # added in two calls, including two distinct items that share a body: every receipt is kept,
    # so the corpus seal still equals the live digest of all the distinct items
    items = [_it("a", "alpha"), _it("b", "beta"), _it("c", "alpha")]  # c shares a body with a
    c = Corpus(str(tmp_path))
    c.add(items[:2])
    c.add(items[2:])
    assert c.digest().seal == digest(items).seal


def test_digest_of_receipts_rejects_a_row_missing_a_field(tmp_path):
    import pytest

    from gather.digest import digest_of_receipts
    with pytest.raises(ValueError, match="missing required field"):
        digest_of_receipts([{"kind": "document", "id": "a"}])  # missing title/source/ref/method/sha256


def test_rows_on_empty_corpus_is_empty(tmp_path):
    assert list(Corpus(str(tmp_path / "fresh")).rows()) == []


def test_stats_summarizes_the_catalog(tmp_path):
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "x", source="web"), _it("b", "y", source="web"),
           _it("c", "z", source="docs")])
    s = c.stats()
    assert s["items"] == 3 and s["distinct_bodies"] == 3
    assert s["by_source"] == {"docs": 1, "web": 2}


def test_prune_detects_and_removes_orphan_objects_only(tmp_path):
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha"), _it("b", "beta")])
    # plant an orphan object: a committed body no catalog row references
    orphan_dir = os.path.join(str(tmp_path), "objects", "ff")
    os.makedirs(orphan_dir, exist_ok=True)
    orphan = os.path.join(orphan_dir, "0" * 62)
    with open(orphan, "w", encoding="utf-8") as f:
        f.write("leftover")

    report = c.prune(apply=False)              # report-only by default
    assert report["orphans"] == 1 and report["removed"] == 0 and report["applied"] is False
    assert os.path.exists(orphan)              # nothing deleted yet

    applied = c.prune(apply=True)
    assert applied["removed"] == 1 and applied["removed_paths"] == [orphan]  # audit trail of the delete
    assert not os.path.exists(orphan)                              # the orphan is gone
    assert os.path.exists(c._object_path(content_hash("alpha")))   # referenced bodies untouched
    assert {i.id for i in [c.load_item(r) for r in c.rows()]} == {"a", "b"}  # corpus intact


def test_prune_never_touches_a_tmp_staging_file(tmp_path):
    # a .tmp may be an in-flight write from a concurrent add; prune must never delete it
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha")])
    shard = os.path.join(str(tmp_path), "objects", "ee")
    os.makedirs(shard, exist_ok=True)
    tmp = os.path.join(shard, ("f" * 62) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("in-flight")
    assert c.prune(apply=False)["orphans"] == 0   # the .tmp is not an orphan
    assert c.prune(apply=True)["removed"] == 0
    assert os.path.exists(tmp)                     # and it is left untouched
