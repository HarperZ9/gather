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

# A YouTube auto-caption file: a line grown across cues (each cue re-emits the previous
# line and extends it), inline timestamp + <c> tags, cue settings on the timing line, a
# NOTE block, a whitespace-only &nbsp; cue, and an HTML entity. The plain text underneath
# is "the quick brown fox jumps" then "over the lazy dog & cat".
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
&nbsp;

00:00:06.000 --> 00:00:08.000 align:start position:0%
the quick brown fox<00:00:04.500><c> jumps</c>

00:00:08.000 --> 00:00:10.000 align:start position:0%
over the lazy dog &amp; cat
"""

# A manual subtitle where one cue legitimately begins with the previous one: collapsing
# this would delete "the group" as a standalone line, so manual subs must not be merged.
MANUAL_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
the group

00:00:02.000 --> 00:00:05.000
the group acts on the set
"""

INFO = json.dumps({
    "id": "abc123", "title": "Test Video", "uploader": "TestChan",
    "duration": 100, "upload_date": "20260101", "view_count": 42,
    "webpage_url": "https://youtu.be/abc123",
    "comments": [{"id": "c1", "text": "great video", "author": "viewer"}],
})


def test_transcript_from_vtt_strips_and_dedups():
    assert transcript_from_vtt(VTT) == "hello world\nthis is a test"


def test_auto_collapses_prefix_growth_strips_tags_and_drops_nbsp():
    # With auto set, each grown cue replaces its predecessor instead of laddering; the NOTE
    # block, inline timestamp/<c> tags, and the &nbsp;-only cue all drop, and &amp; decodes.
    assert transcript_from_vtt(AUTO_VTT, auto=True) == "the quick brown fox jumps\nover the lazy dog & cat"


def test_without_auto_prefix_growth_is_not_collapsed():
    # the prefix-merge is gated to auto: manual mode keeps every distinct line (it ladders)
    lines = transcript_from_vtt(AUTO_VTT, auto=False).splitlines()
    assert lines == ["the quick brown", "the quick brown fox", "the quick brown fox jumps",
                     "over the lazy dog & cat"]


def test_manual_subtitle_prefix_lines_are_preserved():
    # a manual cue that begins with the previous line must not be silently merged away
    assert transcript_from_vtt(MANUAL_VTT) == "the group\nthe group acts on the set"


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


def test_auto_captions_flag_drives_both_the_label_and_the_collapse():
    # one flag stamps the transcript auto-caption AND collapses the rolling window
    items = parse_video(INFO, AUTO_VTT, fetched_at=1.0, auto_captions=True)
    tr = next(i for i in items if i.kind == "transcript")
    assert tr.provenance.method == "auto-caption"          # not stamped as a manual transcript
    assert tr.text == "the quick brown fox jumps\nover the lazy dog & cat"  # collapsed
    meta = next(i for i in items if i.kind == "metadata")
    assert meta.provenance.method == "yt-dlp"              # metadata still stamped by the fetch method


def test_explicit_transcript_method_overrides_the_default():
    items = parse_video(INFO, VTT, fetched_at=1.0, transcript_method="manual-srt")
    tr = next(i for i in items if i.kind == "transcript")
    assert tr.provenance.method == "manual-srt"


def test_parse_video_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_video("{not valid json", None, fetched_at=1.0)
