"""Accountable extraction: Markdown structure, provenance receipt, tamper-evidence."""
from __future__ import annotations

from dataclasses import replace

from gather.extract import Block, extract, to_markdown
from gather.item import content_hash

_FIXTURE = (
    "<html><head><title>Doc</title></head><body>"
    "<h1>Heading</h1>"
    '<p>A <a href="http://e.com">link</a> and <strong>bold</strong> text.</p>'
    "<ul><li>one</li><li>two</li></ul>"
    "<blockquote>quoted</blockquote>"
    "<pre>code here</pre>"
    "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    "</body></html>"
)


def test_markdown_covers_common_structures() -> None:
    md = to_markdown(_FIXTURE)
    assert "# Heading" in md
    assert "[link](http://e.com)" in md
    assert "**bold**" in md
    assert "- one" in md and "- two" in md
    assert "> quoted" in md
    assert "```" in md and "code here" in md
    assert "| A | B |" in md and "| 1 | 2 |" in md


def test_extract_receipt_is_direct_and_verifies() -> None:
    ex = extract(_FIXTURE, "http://e.com/doc", fetched_at=1.0)
    assert ex.title == "Doc"
    # The fetched-vs-inferred boundary: extraction is a DIRECT read, not inference.
    assert ex.method == "html-extract"
    assert ex.blocks  # at least the heading, paragraph, list items...
    assert any(b.tag == "h1" for b in ex.blocks)
    assert ex.verify(_FIXTURE) is True
    # Every block hash re-derives from its own text.
    assert all(content_hash(b.text) == b.sha256 for b in ex.blocks)


def test_tampered_markdown_fails_verification() -> None:
    ex = extract(_FIXTURE, "http://e.com/doc", fetched_at=1.0)
    forged = replace(ex, markdown=ex.markdown + "\n\ninjected claim")
    assert forged.verify(_FIXTURE) is False   # markdown_sha256 no longer matches


def test_tampered_block_fails_verification() -> None:
    ex = extract(_FIXTURE, "http://e.com/doc", fetched_at=1.0)
    original = ex.blocks[0]
    swapped = Block(original.path, original.tag, "a fabricated quote", original.sha256)
    forged = replace(ex, blocks=(swapped,) + ex.blocks[1:])
    assert forged.verify(_FIXTURE) is False   # block text no longer hashes to its sha


def test_altered_source_html_fails_verification() -> None:
    ex = extract(_FIXTURE, "http://e.com/doc", fetched_at=1.0)
    assert ex.verify("<html>different bytes</html>") is False


def test_pre_preserves_code_indentation_and_newlines() -> None:
    html = ("<html><body><pre>def f():\n"
            "    x = 1\n"
            "    return x\n"
            "</pre></body></html>")
    md = to_markdown(html)
    # the fenced block must keep the raw indentation and newlines, not collapse
    # them to a single line of whitespace-normalized text
    assert "def f():\n    x = 1\n    return x" in md


def test_inline_does_not_fuse_words_across_a_nested_block() -> None:
    html = "<html><body><p>alpha<div>beta</div>gamma</p></body></html>"
    md = to_markdown(html)
    # a nested block inside inline context must not weld the words together
    assert "alphabetagamma" not in md
    assert "beta" in md
