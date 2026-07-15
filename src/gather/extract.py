"""Accountable HTML -> Markdown extraction with a per-block provenance receipt.

Firecrawl's headline is turning a page into LLM-ready Markdown; gather does that
too, but attaches a receipt none of the scraping tools carry: every block of
extracted text is bound to its source-node path and content hash, and the whole
Markdown is content-addressed. A later reviewer can re-hash the Markdown and any
block and confirm it is exactly what was extracted, and the ``method`` on the
receipt says the text was READ from the fetched HTML, never inferred, so the
fetched-vs-inferred boundary stays on the record.

Pure and deterministic; sees only server-sent HTML (no JavaScript). Composes with
[dom.py] (the tree) and [track.py] (relocating a block across page versions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from gather.dom import INLINE, SKIP, Node, find, norm, parse_dom
from gather.item import content_hash

_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_INLINE_WRAP = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}
_BLOCK_TAGS = set(_HEADING) | {
    "html", "body", "p", "ul", "ol", "li", "blockquote", "pre", "hr", "table",
    "tr", "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "figure", "figcaption", "dl", "dd", "dt", "form",
}
# Block-level tags whose text is worth a standalone provenance receipt.
_BLOCK_TEXT_TAGS = set(_HEADING) | {
    "p", "li", "blockquote", "pre", "td", "th", "dd", "dt", "figcaption",
}


def _inline(node: Node) -> str:
    """Render a node's inline content to Markdown text (links, emphasis, code,
    images, line breaks). Unknown tags recurse. Nested block elements are
    flattened here; the block emitter handles real structure."""
    out: list[str] = []
    for c in node.content:
        if isinstance(c, str):
            out.append(c)
            continue
        if c.tag in SKIP:
            continue
        if c.tag == "a":
            href = c.attrs.get("href", "")
            txt = norm(_inline(c)) or href
            out.append(f"[{txt}]({href})" if href else txt)
        elif c.tag == "img":
            out.append(f"![{c.attrs.get('alt', '')}]({c.attrs.get('src', '')})")
        elif c.tag in _INLINE_WRAP:
            w = _INLINE_WRAP[c.tag]
            inner = norm(_inline(c))
            out.append(f"{w}{inner}{w}" if inner else "")
        elif c.tag == "br":
            out.append("\n")
        else:
            # a nested non-inline (block) child must not weld its text to the
            # surrounding words: pad it with spaces, mirroring text_content's
            # spacer. norm() collapses any doubled spaces downstream.
            out.append(f" {_inline(c)} " if c.tag not in INLINE else _inline(c))
    return "".join(out)


def _has_block_child(node: Node) -> bool:
    return any(isinstance(c, Node) and c.tag in _BLOCK_TAGS for c in node.content)


def _emit_list(node: Node, lines: list[str], *, ordered: bool) -> None:
    i = 1
    for c in node.children:
        if c.tag != "li":
            continue
        marker = f"{i}." if ordered else "-"
        lines.append(f"{marker} {norm(_inline(c))}".rstrip())
        i += 1


def _emit_table(node: Node, lines: list[str]) -> None:
    rows: list[list[str]] = []
    for tr in (n for n in node.walk() if n.tag == "tr"):
        cells = [norm(_inline(cell)) for cell in tr.children if cell.tag in ("td", "th")]
        if cells:
            rows.append(cells)
    if not rows:
        return
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    lines.append("| " + " | ".join(padded[0]) + " |")
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for r in padded[1:]:
        lines.append("| " + " | ".join(r) + " |")


def _emit_block(node: Node, lines: list[str]) -> None:
    for c in node.content:
        if isinstance(c, str):
            t = norm(c)
            if t:
                lines.extend([t, ""])
            continue
        tag = c.tag
        if tag in SKIP or tag in ("head", "title"):
            continue
        if tag in _HEADING:
            lines.extend(["#" * _HEADING[tag] + " " + norm(_inline(c)), ""])
        elif tag == "p":
            t = norm(_inline(c))
            if t:
                lines.extend([t, ""])
        elif tag in ("ul", "ol"):
            _emit_list(c, lines, ordered=(tag == "ol"))
            lines.append("")
        elif tag == "blockquote":
            inner: list[str] = []
            _emit_block(c, inner)
            lines.extend(("> " + ln if ln else ">") for ln in "\n".join(inner).splitlines())
            lines.append("")
        elif tag == "pre":
            # code: indentation and newlines are content, not layout. Emit the
            # raw subtree text verbatim, never whitespace-normalized.
            lines.extend(["```", c.raw_text().rstrip("\n"), "```", ""])
        elif tag == "hr":
            lines.extend(["---", ""])
        elif tag == "table":
            _emit_table(c, lines)
            lines.append("")
        elif _has_block_child(c):
            _emit_block(c, lines)
        else:
            t = norm(_inline(c))
            if t:
                lines.extend([t, ""])


def to_markdown(html_or_root) -> str:
    """Structured Markdown for a page: headings, paragraphs, lists, links,
    emphasis, code, blockquotes, images, rules, and simple tables. Pure."""
    root = html_or_root if isinstance(html_or_root, Node) else parse_dom(html_or_root)
    lines: list[str] = []
    _emit_block(root, lines)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


@dataclass(frozen=True, slots=True)
class Block:
    """One extracted block of text bound to its source node and content hash."""

    path: str
    tag: str
    text: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Extraction:
    """A re-verifiable extraction receipt. ``method`` records a direct read of
    the fetched HTML, so extracted text is never mistaken for inference."""

    url: str
    method: str
    fetched_at: float
    content_sha256: str
    title: str
    markdown: str
    markdown_sha256: str
    blocks: tuple[Block, ...]

    @property
    def has_content(self) -> bool:
        """False when the extraction found nothing readable (an empty markdown
        and no blocks): a JS-only shell or an unreadable page. The honest null,
        so 'read, found nothing' is not mistaken for a successful extraction."""
        return bool(self.markdown) or bool(self.blocks)

    def verify(self, html: str | None = None) -> bool:
        """Re-hash the Markdown and every block (and the raw HTML if given) and
        confirm nothing was altered after extraction."""
        if content_hash(self.markdown) != self.markdown_sha256:
            return False
        if any(content_hash(b.text) != b.sha256 for b in self.blocks):
            return False
        if html is not None and content_hash(html) != self.content_sha256:
            return False
        return True

    def as_dict(self) -> dict:
        return {
            "url": self.url, "method": self.method, "fetched_at": self.fetched_at,
            "has_content": self.has_content,
            "content_sha256": self.content_sha256, "title": self.title,
            "markdown_sha256": self.markdown_sha256,
            "blocks": [
                {"path": b.path, "tag": b.tag, "sha256": b.sha256} for b in self.blocks
            ],
        }


def extract(html: str, url: str, *, fetched_at: float, method: str = "html-extract") -> Extraction:
    """Extract Markdown plus a per-block provenance receipt from HTML. Pure."""
    root = parse_dom(html)
    title_node = find(root, "title")
    title = title_node.text_content() if title_node else ""
    markdown = to_markdown(root)
    blocks: list[Block] = []
    for n in root.walk():
        if n.tag in _BLOCK_TEXT_TAGS:
            text = n.text_content()
            if text:
                blocks.append(Block(n.path, n.tag, text, content_hash(text)))
    return Extraction(
        url=url, method=method, fetched_at=float(fetched_at),
        content_sha256=content_hash(html), title=title,
        markdown=markdown, markdown_sha256=content_hash(markdown), blocks=tuple(blocks),
    )
