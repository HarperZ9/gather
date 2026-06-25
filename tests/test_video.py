import json

import pytest

from gather.video import parse_video, transcript_from_vtt

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
hello world

00:00:02.000 --> 00:00:04.000
hello world
this is a <c>test</c>
"""

# The real shape of a YouTube auto-caption file: a rolling window where each cue
# repeats the previous line and extends it, plus inline timestamp tags and <c> tags,
# cue settings on the timing line, a NOTE block, and HTML entities. The plain text
# underneath is one sentence: "the quick brown fox jumps over the lazy dog & cat".
AUTO_VTT = """WEBVTT
Kind: captions
Language: en

NOTE
this NOTE block is metadata yt-dlp sometimes writes
and it spans more than one line

00:00:00.000 --> 00:00:02.000 align:start position:0%
the quick<00:00:00.500><c> brown</c>

00:00:02.000 --> 00:00:04.000 align:start position:0%
the quick brown<00:00:02.500><c> fox</c>

00:00:04.000 --> 00:00:06.000 align:start position:0%
the quick brown fox<00:00:04.500><c> jumps</c>

00:00:06.000 --> 00:00:08.000 align:start position:0%
over the lazy dog &amp; cat
"""

INFO = json.dumps({
    "id": "abc123", "title": "Test Video", "uploader": "TestChan",
    "duration": 100, "upload_date": "20260101", "view_count": 42,
    "webpage_url": "https://youtu.be/abc123",
    "comments": [{"id": "c1", "text": "great video", "author": "viewer"}],
})


def test_transcript_from_vtt_strips_and_dedups():
    assert transcript_from_vtt(VTT) == "hello world\nthis is a test"


def test_transcript_from_vtt_collapses_auto_caption_rolling_window():
    # Each rolling cue is a prefix-extension of the one before; the de-ladder collapses
    # them to the single growing line instead of emitting every partial. The NOTE block
    # is dropped, inline timestamp/<c> tags are stripped, and &amp; is decoded.
    assert transcript_from_vtt(AUTO_VTT) == "the quick brown fox jumps\nover the lazy dog & cat"


def test_parse_video_produces_metadata_transcript_and_comment():
    items = parse_video(INFO, VTT, fetched_at=1.0)
    assert sorted(i.kind for i in items) == ["comment", "metadata", "transcript"]
    assert all(i.verify() for i in items)                      # every item has a valid receipt
    assert all(i.provenance.source == "video" for i in items)
    tr = next(i for i in items if i.kind == "transcript")
    assert "hello world" in tr.text and tr.id == "abc123"


def test_parse_video_without_captions_has_no_transcript():
    kinds = {i.kind for i in parse_video(INFO, None, fetched_at=1.0)}
    assert "transcript" not in kinds and "metadata" in kinds


def test_transcript_method_records_auto_captions_as_machine_transcription():
    # an auto-caption transcript must not be stamped as a manual one
    items = parse_video(INFO, VTT, fetched_at=1.0, transcript_method="auto-caption")
    tr = next(i for i in items if i.kind == "transcript")
    assert tr.provenance.method == "auto-caption"
    meta = next(i for i in items if i.kind == "metadata")
    assert meta.provenance.method == "yt-dlp"  # metadata still stamped by the fetch method


def test_parse_video_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_video("{not valid json", None, fetched_at=1.0)
