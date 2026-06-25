import os

from gather.item import content_hash, make_item
from gather.recall import Query, recall, recall_audited
from gather.store import Corpus


def _it(id, text, *, source="web", kind="document", method="http-get", title=None):
    return make_item(kind=kind, id=id, title=title if title is not None else f"T{id}", text=text,
                     source=source, ref=id, method=method, fetched_at=1.0)


def _corpus(tmp_path):
    c = Corpus(str(tmp_path), fsync=False)
    c.add([
        _it("a", "about tiling and monotiles", source="web", kind="webpage", method="http-get"),
        _it("b", "group theory notes", source="docs", kind="document", method="file-read"),
        _it("c", "tiling in crystals", source="arxiv", kind="paper", method="arxiv-api-id"),
        _it("d", "unrelated cooking", source="web", kind="webpage", method="http-get"),
    ])
    return c


def test_recall_everything_with_an_empty_query(tmp_path):
    items = recall(_corpus(tmp_path), Query())
    assert {i.id for i in items} == {"a", "b", "c", "d"}
    assert all(i.verify() for i in items)   # recalled items are reconstructed and re-verifiable


def test_recall_by_source_and_kind(tmp_path):
    items = recall(_corpus(tmp_path), Query(sources=("web",)))
    assert {i.id for i in items} == {"a", "d"}
    items = recall(_corpus(tmp_path), Query(kinds=("paper",)))
    assert {i.id for i in items} == {"c"}


def test_recall_by_terms_matches_title_and_body(tmp_path):
    items = recall(_corpus(tmp_path), Query(terms=("tiling",)))
    assert {i.id for i in items} == {"a", "c"}   # both bodies mention tiling, "b"/"d" do not


def test_recall_term_matches_in_the_title_only(tmp_path):
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("t", "no keyword in the body", title="A study of Penrose tilings")])
    assert {i.id for i in recall(c, Query(terms=("penrose",)))} == {"t"}  # title-only match works


def test_recall_terms_are_unanchored_substrings(tmp_path):
    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("x", "a cartesian plane")])
    assert {i.id for i in recall(c, Query(terms=("art",)))} == {"x"}  # 'art' matches 'cartesian'


def test_recall_multiple_values_in_a_filter_are_or(tmp_path):
    items = recall(_corpus(tmp_path), Query(sources=("web", "arxiv")))
    assert {i.id for i in items} == {"a", "c", "d"}  # web OR arxiv


def test_recall_combines_filters_with_and(tmp_path):
    # tiling AND source=web -> only "a" (c is tiling but arxiv; d is web but not tiling)
    items = recall(_corpus(tmp_path), Query(terms=("tiling",), sources=("web",)))
    assert {i.id for i in items} == {"a"}


def test_recall_by_method(tmp_path):
    items = recall(_corpus(tmp_path), Query(methods=("arxiv-api-id",)))
    assert {i.id for i in items} == {"c"}


def test_recall_limit_stops_early_and_preserves_order(tmp_path):
    items = recall(_corpus(tmp_path), Query(), limit=2)
    assert [i.id for i in items] == ["a", "b"]   # first two in catalog order


def test_recall_limit_zero_or_negative_returns_nothing(tmp_path):
    c = _corpus(tmp_path)
    assert recall(c, Query(), limit=0) == []
    assert recall(c, Query(), limit=-1) == []


def test_recall_skips_and_reports_a_missing_body(tmp_path):
    c = _corpus(tmp_path)
    os.remove(c._object_path(content_hash("group theory notes")))  # delete b's body
    items, skipped = recall_audited(c, Query())
    assert {i.id for i in items} == {"a", "c", "d"}     # b skipped, not a crash
    assert [s["id"] for s in skipped] == ["b"] and skipped[0]["status"] == "MISSING"


def test_recall_skips_and_reports_a_corrupt_body(tmp_path):
    c = _corpus(tmp_path)
    with open(c._object_path(content_hash("group theory notes")), "w", encoding="utf-8") as f:
        f.write("tampered")                              # b's body no longer hashes to its receipt
    items, skipped = recall_audited(c, Query())
    assert "b" not in {i.id for i in items}              # a tampered body is never returned
    assert [s["id"] for s in skipped] == ["b"] and skipped[0]["status"] == "CORRUPT"


def test_recall_reports_a_non_hex_sha_as_corrupt_agreeing_with_verify(tmp_path):
    # a tampered (non-hex) sha must get the same verdict from recall and from corpus verify
    import json as _json

    c = Corpus(str(tmp_path), fsync=False)
    c.add([_it("a", "alpha")])
    with open(c._catalog, encoding="utf-8") as f:
        row = _json.loads(f.readline())
    row["sha256"] = "../../etc/passwd"
    with open(c._catalog, "w", encoding="utf-8") as f:
        f.write(_json.dumps(row) + "\n")
    recall_status = recall_audited(c, Query())[1][0]["status"]
    verify_status = c.verify()[0]["status"]
    assert recall_status == verify_status == "CORRUPT"   # both agree: tampering, not absence
