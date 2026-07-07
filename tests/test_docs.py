from pathlib import Path

import pytest

from gather.docs import DocsSource, document_item


def test_flagship_brand_assets_exist_and_are_referenced():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    for rel in [
        "docs/brand/gather-mark.svg",
        "docs/brand/gather-hero.png",
        "examples/gather-demo.html",
        ".github/assets/banner.svg",
    ]:
        assert (root / rel).exists(), rel
    for rel in [
        ".github/assets/banner.svg",
        "examples/gather-demo.html",
    ]:
        assert rel in readme
    assert "## Why it matters" in readme
    assert "## Work with it" in readme
    hero = (root / "docs/brand/gather-hero.svg").read_text(encoding="utf-8")
    assert "<title" in hero
    assert "<desc" in hero
    assert "#f4f3ef" in hero


def test_document_item_is_receipted():
    it = document_item("a.md", "# hi", fetched_at=1.0, ref="/abs/a.md")
    assert it.kind == "document" and it.provenance.source == "docs"
    assert it.provenance.method == "file-read"
    assert it.verify() is True


def test_docs_source_reads_a_single_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("hello docs", encoding="utf-8")
    items = DocsSource().fetch(str(f))
    assert len(items) == 1
    assert items[0].text == "hello docs" and items[0].id == "note.md"
    assert items[0].verify()


def test_docs_source_walks_a_directory_deterministically(tmp_path):
    (tmp_path / "b.txt").write_text("bee", encoding="utf-8")
    (tmp_path / "a.txt").write_text("ay", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("cee", encoding="utf-8")
    (tmp_path / "skip.bin").write_text("nope", encoding="utf-8")  # non-text extension, skipped
    items = DocsSource().fetch(str(tmp_path))
    assert [i.id for i in items] == ["a.txt", "b.txt", "sub/c.md"]  # sorted, recursive, .bin skipped
    assert all(i.verify() for i in items)


def test_docs_source_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        DocsSource().fetch(str(tmp_path / "nope"))
