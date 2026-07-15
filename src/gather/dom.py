"""Zero-dependency HTML DOM: a small tree with stable node paths and CSS-lite
selection.

The substrate for accountable extraction ([extract.py]) and witnessable adaptive
element tracking ([track.py]). Pure stdlib (``html.parser``); it sees only the
HTML the server sent, never a JavaScript-rendered page, so a receipt built on it
records a raw parse, not a claim of a rendered DOM.

Order is preserved: each node keeps an ordered ``content`` list of child Nodes
and text strings interleaved, so the readable text of ``<p>Hello <b>world</b>!``
is ``Hello world!`` and never reordered. Node identity is object identity
(``eq=False``), so paths and selection stay stable under structurally-equal
siblings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Elements that never have a close tag; they take no children.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# Subtrees whose text is not readable content.
SKIP = {"script", "style", "noscript", "template"}

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"([.#]?)([\w-]+|\*)")
# Inline elements do not introduce a text boundary; everything else (block
# elements, br, ...) inserts a space so words never merge across a tag edge.
INLINE = {
    "a", "b", "strong", "i", "em", "code", "span", "small", "sub", "sup", "u",
    "mark", "abbr", "cite", "q", "label", "time", "bdi", "bdo", "kbd", "samp", "var",
}


def norm(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip. Pure."""
    return _WS.sub(" ", text).strip()


@dataclass(slots=True, eq=False)
class Node:
    """One HTML element. ``content`` interleaves child Nodes and text strings in
    document order; ``children`` is the Node subset. Equality is identity."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: "Node | None" = None
    content: list = field(default_factory=list)
    pos: int = 0  # 1-based index among same-tag siblings, assigned at parse time

    @property
    def node_id(self) -> str:
        return self.attrs.get("id", "")

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(self.attrs.get("class", "").split())

    @property
    def children(self) -> list["Node"]:
        return [c for c in self.content if isinstance(c, Node)]

    @property
    def path(self) -> str:
        """A stable, 1-based, tag-scoped path from the root, e.g.
        ``html[1]/body[1]/div[2]/p[1]``. The root sentinel has an empty path.
        ``pos`` is assigned once at parse time, so this is O(depth), not O(n)."""
        if self.parent is None:
            return ""
        prefix = self.parent.path
        seg = f"{self.tag}[{self.pos}]"
        return f"{prefix}/{seg}" if prefix else seg

    def text_content(self) -> str:
        """Readable, whitespace-normalized text of this subtree in document
        order, dropping script/style/etc. Pure and deterministic."""
        parts: list[str] = []

        def rec(n: "Node") -> None:
            if n.tag in SKIP:
                return
            for c in n.content:
                if isinstance(c, str):
                    parts.append(c)
                else:
                    spacer = c.tag not in INLINE
                    if spacer:
                        parts.append(" ")
                    rec(c)
                    if spacer:
                        parts.append(" ")

        rec(self)
        return norm("".join(parts))

    def raw_text(self) -> str:
        """The subtree's string leaves in document order, VERBATIM: no
        whitespace normalization. For <pre>/code, where indentation and
        newlines are content, not layout. Drops SKIP subtrees only."""
        parts: list[str] = []

        def rec(n: "Node") -> None:
            if n.tag in SKIP:
                return
            for c in n.content:
                if isinstance(c, str):
                    parts.append(c)
                else:
                    rec(c)

        rec(self)
        return "".join(parts)

    def walk(self):
        """Yield this node then every descendant, document order."""
        yield self
        for c in self.children:
            yield from c.walk()


class _DOMBuilder(HTMLParser):
    """Builds a forgiving Node tree. Unclosed tags are closed implicitly when an
    ancestor closes; a stray end tag is ignored. Not spec-perfect HTML5, but
    stable and good enough for extraction over real-world markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self._stack: list[Node] = [self.root]
        self._counts: dict[int, dict[str, int]] = {}  # id(parent) -> {tag: count}

    def _make(self, tag, attrs) -> Node:
        parent = self._stack[-1]
        counts = self._counts.setdefault(id(parent), {})
        counts[tag] = counts.get(tag, 0) + 1
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent, pos=counts[tag])
        parent.content.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._make(tag, attrs)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._make(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1].content.append(data)


def parse_dom(html: str) -> Node:
    """Parse HTML into a Node tree rooted at a ``#root`` sentinel. Pure."""
    builder = _DOMBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _descendants(node: Node):
    for c in node.content:
        if isinstance(c, Node):
            yield c
            yield from _descendants(c)


def _matches_simple(node: Node, part: str) -> bool:
    """Match one compound simple selector. Tag, ``#id``, and ``.class`` tokens may
    appear in any order (``div.note#lead`` == ``div#lead.note``)."""
    if not part:
        return False
    tag: str | None = None
    want_id: str | None = None
    classes: set[str] = set()
    matched = ""
    for m in _TOKEN.finditer(part):
        matched += m.group(0)
        sigil, name = m.group(1), m.group(2)
        if sigil == "#":
            want_id = name
        elif sigil == ".":
            classes.add(name)
        else:
            tag = name
    if matched != part:  # stray characters -> not a selector we understand
        return False
    if tag and tag != "*" and node.tag != tag:
        return False
    if want_id and node.node_id != want_id:
        return False
    if classes and not classes.issubset(set(node.classes)):
        return False
    return True


def select(root: Node, selector: str) -> list[Node]:
    """CSS-lite selection: descendant combinator (whitespace) over compound
    simple selectors ``tag``, ``#id``, ``.class``, and combinations
    (``div.note#lead``). Returns descendants in document order, de-duplicated.
    Deliberately small: enough to bind an extraction to a selector, not a full
    CSS engine."""
    current = [root]
    for part in selector.split():
        seen: set[int] = set()
        nxt: list[Node] = []
        for m in current:
            for n in _descendants(m):
                if id(n) not in seen and _matches_simple(n, part):
                    seen.add(id(n))
                    nxt.append(n)
        current = nxt
    return current


def find(root: Node, selector: str) -> Node | None:
    """First match of ``selector``, or None."""
    hits = select(root, selector)
    return hits[0] if hits else None
