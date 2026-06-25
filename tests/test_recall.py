from gather.item import make_item
from gather.recall import Query, recall
from gather.store import Corpus


def _it(id, text, *, source="web", kind="document", method="http-get"):
    return make_item(kind=kind, id=id, title=f"T{id}", text=text,
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
