import pytest

from gather.pdf import PdfSource, pdf_item


def test_pdf_item_is_receipted():
    it = pdf_item("paper.pdf", "extracted text", fetched_at=1.0, ref="/abs/paper.pdf")
    assert it.kind == "paper" and it.provenance.source == "pdf"
    assert it.provenance.method == "pdftotext"   # a tool's reading, honestly labelled
    assert it.verify() is True


def test_pdf_source_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        PdfSource().fetch(str(tmp_path / "nope.pdf"))
