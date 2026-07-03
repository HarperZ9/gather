"""Optional native-speed parsing that produces the SAME gather Node tree.

The stdlib parser ([dom.py]) is the zero-dep default. When ``lxml`` is installed,
``parse_best`` builds the identical gather Node tree (same tag-scoped paths) from
lxml's C tokenizer, which is faster on large documents. The tree shape and node
paths match the stdlib parser, so a fingerprint, extraction receipt, or crawl
built one way relocates and verifies the same way, as long as one parser is used
consistently for a given artifact (text whitespace can differ slightly between
tokenizers, which changes content hashes but not structure).

This is wedge 5's fast-parse backend: a real capability win, kept honest by
producing the same accountable structure rather than a different one.
"""
from __future__ import annotations

from gather.backends import detect_fast_parse
from gather.dom import Node, parse_dom


def _attach(lx_el, parent: Node, sibling_counts: dict) -> None:
    tag = lx_el.tag
    if not isinstance(tag, str):  # comments / processing instructions
        return
    tag = tag.lower()
    sibling_counts[tag] = sibling_counts.get(tag, 0) + 1
    node = Node(
        tag, {k: (v or "") for k, v in lx_el.attrib.items()}, parent,
        pos=sibling_counts[tag],
    )
    parent.content.append(node)
    child_counts: dict = {}
    if lx_el.text:
        node.content.append(lx_el.text)
    for child in lx_el.iterchildren():
        _attach(child, node, child_counts)
        if isinstance(child.tag, str) and child.tail:
            node.content.append(child.tail)
        elif not isinstance(child.tag, str) and child.tail:
            node.content.append(child.tail)


def parse_dom_lxml(html: str) -> Node:
    """Build a gather Node tree using lxml. Requires lxml. Paths match the stdlib
    parser for well-formed markup."""
    from lxml import etree  # type: ignore

    root = Node("#root")
    if not html.strip():
        return root
    lx = etree.fromstring(html, etree.HTMLParser())
    if lx is not None:
        _attach(lx, root, {})
    return root


def parse_best(html: str) -> Node:
    """Parse with the native backend if one is installed, else the stdlib parser.
    Returns an equivalent gather Node tree either way."""
    if detect_fast_parse() == "lxml":
        return parse_dom_lxml(html)
    # selectolax path could go here; until then, stdlib is the honest fallback.
    return parse_dom(html)
