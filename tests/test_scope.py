from gather.item import make_item
from gather.scope import filter_scope, in_scope


def _it(title, text):
    return make_item(kind="transcript", id="x", title=title, text=text,
                     source="s", ref="x", method="m", fetched_at=1.0)


def test_in_scope_matches_title_or_text_case_insensitive():
    it = _it("On Rubik Cubes", "group theory")
    assert in_scope(it, ["rubik"]) is True
    assert in_scope(it, ["GROUP"]) is True
    assert in_scope(it, ["knitting"]) is False


def test_empty_terms_keep_everything():
    assert in_scope(_it("a", "b"), []) is True


def test_filter_scope_reports_dropped_count():
    items = [_it("alpha", ""), _it("beta", ""), _it("gamma", "")]
    kept, dropped = filter_scope(items, ["alpha", "gamma"])
    assert [i.title for i in kept] == ["alpha", "gamma"]
    assert dropped == 1
