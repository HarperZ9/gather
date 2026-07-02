"""Zero-dep DOM: tree building, stable paths, ordered text, CSS-lite selection."""
from __future__ import annotations

from gather.dom import find, parse_dom, select


def test_parse_builds_tree_and_paths() -> None:
    root = parse_dom("<html><body><div><p>a</p><p>b</p></div></body></html>")
    ps = select(root, "p")
    assert [p.path for p in ps] == [
        "html[1]/body[1]/div[1]/p[1]",
        "html[1]/body[1]/div[1]/p[2]",
    ]


def test_text_content_preserves_document_order() -> None:
    root = parse_dom("<p>Hello <b>world</b>!</p>")
    assert find(root, "p").text_content() == "Hello world!"


def test_skip_subtrees_are_not_readable() -> None:
    root = parse_dom("<div>keep<script>drop()</script><style>x{}</style></div>")
    assert find(root, "div").text_content() == "keep"


def test_void_elements_take_no_children() -> None:
    root = parse_dom("<p>before<br>after</p>")
    p = find(root, "p")
    assert [c.tag for c in p.children] == ["br"]
    assert p.text_content() == "before after"


def test_select_by_tag_class_id_and_compound() -> None:
    html = '<div class="a note" id="lead"><span class="a">x</span></div>'
    root = parse_dom(html)
    assert find(root, "#lead").tag == "div"
    assert len(select(root, ".a")) == 2          # div and span both have class a
    assert len(select(root, "div.note")) == 1
    assert find(root, "div.note#lead") is not None


def test_select_descendant_combinator() -> None:
    root = parse_dom("<div class='c'><span><a href='#'>x</a></span></div><a>y</a>")
    hits = select(root, ".c a")
    assert len(hits) == 1
    assert hits[0].text_content() == "x"
