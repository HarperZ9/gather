import hashlib
import json
import os
from pathlib import Path

from gather.digest import digest, digest_of_receipts, verify_digest
from gather.item import content_hash, make_item
from gather.store import CORRUPT, LEGACY_COMPATIBLE, MATCH, MISSING, Corpus


def _it(id, text, source="web"):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source=source, ref=id, method="http-get", fetched_at=1.0)


def _legacy_windows_text_bytes(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("utf-8")


def _append_legacy_row(c: Corpus, item, raw: bytes) -> None:
    path = Path(c._object_path(item.provenance.sha256))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    Path(c._catalog).parent.mkdir(parents=True, exist_ok=True)
    with open(c._catalog, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(Corpus._row(item), ensure_ascii=False, sort_keys=True) + "\n")


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


def test_new_rows_store_newline_text_as_exact_utf8_and_seal_storage(tmp_path):
    # Catches: text-mode writes changing source newlines and storage metadata being dropped from the seal.
    cases = {
        "lf": "alpha\nbeta",
        "crlf": "alpha\r\nbeta",
        "cr": "alpha\rbeta",
        "mixed": "snowman ☃\r\nbeta\ngamma\rdelta",
    }
    items = [_it(ident, text) for ident, text in cases.items()]
    c = Corpus(str(tmp_path), fsync=False)
    c.add(items)

    rows = list(c.rows())
    by_id = {row["id"]: row for row in rows}
    for ident, text in cases.items():
        row = by_id[ident]
        raw = Path(c._object_path(row["sha256"])).read_bytes()
        assert raw == text.encode("utf-8")
        assert c.read_text(row["sha256"]) == text
        assert row["storage"] == {
            "schema": "gather.storage/v1",
            "codec": "utf8-exact/v1",
            "object_sha256": hashlib.sha256(raw).hexdigest(),
        }

    results = {row["id"]: row for row in c.verify()}
    assert {row["status"] for row in results.values()} == {MATCH}
    assert {row["storage_status"] for row in results.values()} == {"MATCH"}
    assert {row["storage_witnessed"] for row in results.values()} == {True}

    storage_sealed = c.digest()
    provenance_only = digest(items)
    stripped = [{k: v for k, v in row.items() if k != "storage"} for row in rows]
    assert verify_digest(storage_sealed) is True
    assert storage_sealed.seal != provenance_only.seal
    assert digest_of_receipts(stripped).seal == provenance_only.seal

    tampered_storage = dict(rows[0])
    tampered_storage["storage"] = dict(rows[0]["storage"], object_sha256="0" * 64)
    assert digest_of_receipts([tampered_storage, *rows[1:]]).seal != storage_sealed.seal


def test_add_refuses_preexisting_corrupt_object_before_catalog_append(tmp_path):
    # Catches: adding a receipt that reuses a corrupt preexisting object by silently dropping
    # the new storage witness instead of refusing before the catalog append.
    item = _it("lf", "A\nB")
    c = Corpus(str(tmp_path), fsync=False)
    object_path = Path(c._object_path(item.provenance.sha256))
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(b"A\rB")

    import pytest
    with pytest.raises(ValueError, match="preexisting object does not match receipt"):
        c.add([item])

    assert list(c.rows()) == []
    assert object_path.read_bytes() == b"A\rB"


def test_add_preserves_valid_preexisting_legacy_object_without_rewriting(tmp_path):
    # Catches: rejecting or rewriting an existing legacy Windows text object that reconstructs
    # exactly one source text for an unwitnessed legacy row.
    item = _it("lf", "A\nB")
    legacy_raw = _legacy_windows_text_bytes(item.text)
    c = Corpus(str(tmp_path), fsync=False)
    object_path = Path(c._object_path(item.provenance.sha256))
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(legacy_raw)

    assert c.add([item]) == {"added": 1, "deduped": 0, "total": 1}

    row = next(c.rows())
    assert "storage" not in row
    assert object_path.read_bytes() == legacy_raw
    assert c.read_text(row["sha256"]) == "A\nB"
    loaded = c.load_item(row)
    assert loaded.text == "A\nB"
    assert loaded.verify()
    result = c.verify()[0]
    assert result["status"] == MATCH
    assert result["storage_status"] == LEGACY_COMPATIBLE
    assert result["storage_witnessed"] is False


def test_legacy_windows_text_rows_reconstruct_source_without_raw_integrity_claim(tmp_path):
    # Catches: refusing old Windows-written records that can still reconstruct exactly one source text.
    cases = {
        "lf": "legacy\nbody",
        "crlf": "legacy\r\nbody",
        "cr": "legacy\rbody",
        "mixed": "unicode µ\r\nlegacy\nbody\rtail",
    }
    items = [_it(ident, text) for ident, text in cases.items()]
    c = Corpus(str(tmp_path), fsync=False)
    for item in items:
        _append_legacy_row(c, item, _legacy_windows_text_bytes(item.text))

    rows = list(c.rows())
    assert all("storage" not in row for row in rows)
    assert c.digest().seal == digest(items).seal

    for row in rows:
        assert c.read_text(row["sha256"]) == cases[row["id"]]
        loaded = c.load_item(row)
        assert loaded.text == cases[row["id"]]
        assert loaded.verify()

    results = {row["id"]: row for row in c.verify()}
    assert {row["status"] for row in results.values()} == {MATCH}
    assert {row["storage_status"] for row in results.values()} == {"LEGACY_COMPATIBLE"}
    assert {row["storage_witnessed"] for row in results.values()} == {False}


def test_legacy_lone_cr_mutation_no_longer_verifies_as_lf_receipt(tmp_path):
    # Catches: universal-newline reads accepting a lone-CR body as if it were the LF source receipt.
    item = _it("lf", "line one\nline two")
    c = Corpus(str(tmp_path), fsync=False)
    _append_legacy_row(c, item, b"line one\rline two")

    assert c.verify()[0]["status"] == CORRUPT
    import pytest
    with pytest.raises(ValueError, match="stored body does not match receipt"):
        c.read_text(item.provenance.sha256)


def test_new_storage_witness_rejects_newline_mutated_object(tmp_path):
    # Catches: accepting CRLF or CR mutation of a newly witnessed exact-UTF-8 object.
    item = _it("lf", "line one\nline two")
    c = Corpus(str(tmp_path), fsync=False)
    c.add([item])
    row = next(c.rows())
    Path(c._object_path(row["sha256"])).write_bytes(b"line one\r\nline two")

    result = c.verify()[0]
    assert result["status"] == CORRUPT
    assert result["storage_status"] == CORRUPT
    assert result["storage_witnessed"] is True
    import pytest
    with pytest.raises(ValueError, match="stored body does not match receipt"):
        c.read_text(row["sha256"])
    with pytest.raises(ValueError, match="stored body does not match receipt"):
        c.load_item(row)


def test_corpus_digest_matches_a_direct_digest(tmp_path):
    items = [_it("a", "alpha"), _it("b", "beta")]
    c = Corpus(str(tmp_path))
    c.add(items)
    d = c.digest()
    assert verify_digest(d) is True
    assert d.seal != digest(items).seal   # new rows also seal their exact storage witness


def test_corpus_digest_matches_across_multiple_adds_and_shared_bodies(tmp_path):
    # added in two calls, including two distinct items that share a body: every receipt is kept,
    # and the stored corpus seal adds storage witnesses to the live item provenance digest.
    items = [_it("a", "alpha"), _it("b", "beta"), _it("c", "alpha")]  # c shares a body with a
    c = Corpus(str(tmp_path))
    c.add(items[:2])
    c.add(items[2:])
    assert c.digest().seal != digest(items).seal


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


def test_verify_reports_a_field_missing_row_as_corrupt_not_a_crash(tmp_path):
    import json as _json

    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha")])
    with open(c._catalog, "a", encoding="utf-8") as f:
        f.write(_json.dumps({"id": "b", "kind": "document"}) + "\n")  # a row with no sha256
    by_id = {r["id"]: r["status"] for r in c.verify()}
    assert by_id["a"] == MATCH and by_id["b"] == CORRUPT   # the malformed row is reported, not fatal


def test_prune_refuses_when_catalog_is_empty_but_bodies_exist(tmp_path):
    import pytest

    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha")])
    # simulate a torn write: bodies present, catalog truncated to empty
    open(c._catalog, "w", encoding="utf-8").close()
    assert c.prune(apply=False)["orphans"] >= 1          # report is fine
    with pytest.raises(ValueError, match="refusing to prune"):
        c.prune(apply=True)                              # but refuse to delete every body
    assert os.path.exists(c._object_path(content_hash("alpha")))  # body survived


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
