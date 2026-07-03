"""Optional native-speed parsing that produces the SAME gather Node tree.

The stdlib parser ([dom.py]) is the zero-dep default. When ``lxml`` is installed,
``parse_best`` builds the SAME gather Node tree (identical tag-scoped paths) from
lxml's C tokenizer, which is faster on large documents. lxml wraps a bare fragment
in a synthetic ``html``/``body``; this module unwraps that wrapper when the source
did not contain one, so a fragment like ``<p>x</p>`` yields the same ``p[1]`` path
as the stdlib parser, not ``html[1]/body[1]/p[1]``. Node paths therefore match
either backend, so a fingerprint, extraction receipt, or crawl built one way
relocates and verifies the same way (text whitespace can differ slightly between
tokenizers, which changes content hashes but not structure; use one parser
consistently for a given artifact).

This is wedge 5's fast-parse backend: a real capability win, kept honest by
producing the same accountable structure rather than a different one.
"""
from __future__ import annotations

import re

from gather.backends import detect_fast_parse
from gather.dom import Node, parse_dom

_HAS_HTML = re.compile(r"<\s*(html|!doctype)", re.I)
_HAS_BODY = re.compile(r"<\s*body", re.I)


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
        if child.tail:
            node.content.append(child.tail)


def parse_dom_lxml(html: str) -> Node:
    """Build a gather Node tree using lxml, unwrapping the synthetic html/body lxml
    adds around a bare fragment so paths match the stdlib parser. Requires lxml."""
    from lxml import etree  # type: ignore

    root = Node("#root")
    if not html.strip():
        return root
    lx = etree.fromstring(html, etree.HTMLParser())
    if lx is None:
        return root
    # lxml auto-wraps a fragment in <html><body>. If the source had neither, attach
    # the real content directly under #root so node paths match the stdlib parser.
    if isinstance(lx.tag, str) and lx.tag == "html" and not _HAS_HTML.search(html):
        counts: dict = {}
        for section in lx:
            stag = section.tag if isinstance(section.tag, str) else ""
            if stag == "body" and not _HAS_BODY.search(html):
                if section.text:
                    root.content.append(section.text)
                for child in section.iterchildren():
                    _attach(child, root, counts)
            elif stag == "head" and not _HAS_HTML.search(html):
                for child in section.iterchildren():
                    _attach(child, root, counts)
            else:
                _attach(section, root, counts)
        return root
    _attach(lx, root, {})
    return root


def parse_best(html: str) -> Node:
    """Parse with the native backend if one is installed, else the stdlib parser.
    Returns an equivalent gather Node tree either way."""
    if detect_fast_parse() == "lxml":
        return parse_dom_lxml(html)
    # selectolax path could go here; until then, stdlib is the honest fallback.
    return parse_dom(html)
