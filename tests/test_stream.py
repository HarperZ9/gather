"""Streaming partial-update extraction: stable commits, pending tail, determinism."""
from __future__ import annotations

from dataclasses import replace

from gather.item import content_hash
from gather.stream import StreamingExtractor, StreamLedger, stream_extract


def test_blocks_commit_as_they_close_and_tail_stays_pending() -> None:
    sx = StreamingExtractor()
    c1 = sx.feed("<html><body><h1>Title</h1>")
    assert [c.tag for c in c1] == ["h1"] and c1[0].text == "Title"

    c2 = sx.feed("<p>partial text stil")
    assert c2 == []                    # the p has not closed: nothing witnessed
    assert "p" in sx.pending()         # it is the incomplete tail

    c3 = sx.feed("l streaming</p><p>second</p>")
    assert [c.tag for c in c3] == ["p", "p"]
    assert c3[0].text == "partial text still streaming"   # buffered across chunks
    assert c3[1].text == "second"
    assert sx.pending() == ["html", "body"]               # only containers open


def test_chunk_boundaries_do_not_change_the_ledger() -> None:
    doc = "<html><body><h1>H</h1><p>alpha</p><ul><li>one</li><li>two</li></ul></body></html>"

    def key(led):
        return [(c.seq, c.path, c.tag, c.sha256) for c in led.commits]

    whole = stream_extract([doc])
    charwise = stream_extract(list(doc))          # worst case: split mid-tag everywhere
    assert key(whole) == key(charwise)
    assert whole.root_hash == charwise.root_hash
    assert [c.tag for c in whole.commits] == ["h1", "p", "li", "li"]


def test_ledger_verifies_and_tamper_is_detected() -> None:
    led = stream_extract(["<body><p>a</p><p>b</p></body>"])
    assert led.verify() is True
    bad = replace(led.commits[0], text="x", sha256=content_hash("x"))
    tampered = StreamLedger((bad,) + tuple(led.commits[1:]), led.root_hash)
    assert tampered.verify() is False


def test_unclosed_block_is_never_witnessed() -> None:
    sx = StreamingExtractor()
    sx.feed("<body><p>done</p><p>truncated tail")
    final = sx.close()
    assert final == []                                   # nothing new committed on flush
    assert [c.tag for c in sx.ledger().commits] == ["p"]  # only the closed block
    assert sx.ledger().commits[0].text == "done"


def test_stream_ledger_reassembles_markdown() -> None:
    led = stream_extract(["<body><h1>Title</h1><p>body text</p></body>"])
    assert "# Title" in led.markdown()
    assert "body text" in led.markdown()
