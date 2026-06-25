import pytest

from gather.browser import BrowserSource, parse_browser
from gather.ocr import OcrSource, ocr_item
from gather.transcribe import TranscribeSource, transcribe_item


def test_parse_browser_marks_javascript_was_run():
    it = parse_browser("<title>T</title><body><p>rendered text</p></body>",
                       "https://example.com/app", fetched_at=1.0)
    assert it.kind == "webpage" and it.provenance.source == "browser"
    assert it.provenance.method == "browser-extract"   # distinct from web's http-get: JS was executed
    assert "rendered text" in it.text and it.title == "T"
    assert it.verify()


def test_browser_refuses_non_http_and_private_hosts():
    for bad in ("file:///etc/passwd", "http://127.0.0.1/", "http://169.254.169.254/"):
        with pytest.raises(ValueError):
            BrowserSource().fetch(bad)


def test_ocr_item_is_receipted_as_a_machine_reading():
    it = ocr_item("scan.png", "recognized words", fetched_at=1.0, ref="/abs/scan.png")
    assert it.kind == "document" and it.provenance.source == "ocr"
    assert it.provenance.method == "ocr"
    assert it.verify()


def test_ocr_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        OcrSource().fetch(str(tmp_path / "nope.png"))


def test_transcribe_item_is_a_machine_transcript():
    it = transcribe_item("talk.mp3", "the spoken words", fetched_at=1.0, ref="/abs/talk.mp3")
    assert it.kind == "transcript" and it.provenance.source == "transcribe"
    assert it.provenance.method == "transcribe"
    assert it.verify()


def test_transcribe_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        TranscribeSource().fetch(str(tmp_path / "nope.mp3"))
