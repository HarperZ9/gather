import json

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

INFO = json.dumps({
    "id": "abc123", "title": "Test Video", "uploader": "TestChan",
    "duration": 100, "upload_date": "20260101", "view_count": 42,
    "webpage_url": "https://youtu.be/abc123",
    "comments": [{"id": "c1", "text": "great video", "author": "viewer"}],
})


def test_transcript_from_vtt_strips_and_dedups():
    assert transcript_from_vtt(VTT) == "hello world\nthis is a test"


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
