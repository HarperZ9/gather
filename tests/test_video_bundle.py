"""The video bundle: every file written, SHA256SUMS re-checked, no stream address kept, replies under
their parents, and the live edge driven through a scripted yt-dlp (media only when asked for)."""

import hashlib
import json
import os

from fake_ytdlp import BOT_CHECK, FakeYtDlp, video_info

from gather.video_bundle import (
    comment_tree,
    comments_text,
    plain_transcript,
    timed_transcript,
    vtt_segments,
)
from gather.video_bundle_cmd import comments_from_file
from gather.video_bundle_run import fetch_bundle, write_bundle
from gather.video_source import VideoSource
from gather.ytdlp import CallResult

AUTO_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
what if<00:00:00.500><c> there</c>

00:00:02.000 --> 00:00:02.010
what if there

00:00:02.010 --> 00:00:04.000
what if there
is no hard<00:00:03.000><c> problem</c>
"""

INFO = {
    "id": "vid00000001", "title": "A talk", "channel": "Chan", "uploader_id": "@chan", "upload_date": "20261102",
    "webpage_url": "https://www.youtube.com/watch?v=vid00000001", "comment_count": 3,
    "chapters": [{"start_time": 0, "title": "Cold open"}, {"start_time": 111, "title": "Introduction"}],
    "formats": [{"url": "https://rr1---sn.googlevideo.com/videoplayback?ip=203.0.113.9"}],
    "comments": [
        {"id": "A", "parent": "root", "text": "Representing an observer does not explain it, because the attribution is missing.",
         "like_count": 20, "author": "@alice"},
        {"id": "A.1", "parent": "A", "text": "Exactly, and clinical cases where actions stop feeling like one's own show it.",
         "like_count": 2, "author": "@bob"},
        {"id": "B", "parent": "root", "text": "Great talk", "like_count": 1, "author": "@carol"},
    ],
}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_machine_captions_keep_each_line_once_with_times():
    segs = vtt_segments(AUTO_VTT)
    assert [s["text"] for s in segs] == ["what if there", "is no hard problem"]
    assert timed_transcript(segs) == "[00:00:00] what if there\n[00:00:02] is no hard problem\n"
    assert plain_transcript(segs) == "what if there is no hard problem\n"


def test_replies_sit_under_their_parent_and_the_text_names_no_one():
    tree = comment_tree(INFO["comments"])
    assert [n["id"] for n in tree] == ["A", "B"]
    assert tree[0]["replies"][0]["id"] == "A.1"
    text = comments_text(tree)
    assert "   > [2] Exactly" in text and "@alice" not in text and "@bob" not in text
    orphan = comment_tree([{"id": "Z.1", "parent": "Z", "text": "x"}])
    assert orphan[0]["parent_missing"] is True


def test_the_bundle_holds_every_part_and_its_hashes_check(tmp_path):
    out = str(tmp_path / "b")
    os.makedirs(out)
    open(os.path.join(out, "vid00000001.mp4"), "wb").write(b"not really a video")
    res = write_bundle(out, INFO, vtt=AUTO_VTT, caption={"lang": "en-orig", "kind": "auto", "from": "yt-dlp WebVTT"},
                       media="vid00000001.mp4", fetched_at=1793750400.0)
    names = set(os.listdir(out))
    for f in ("vid00000001.en-orig.vtt", "vid00000001.transcript.txt", "vid00000001.transcript.plain.txt", "vid00000001.thread.json",
              "vid00000001.comments.txt", "vid00000001.video.json", "vid00000001.balance.json", "vid00000001.balance.md",
              "SOURCE.txt", "SHA256SUMS"):
        assert f in names, f
    lines = open(os.path.join(out, "SHA256SUMS"), encoding="utf-8").read().splitlines()
    assert len(lines) == len(names) - 1, "every file but SHA256SUMS itself"
    for line in lines:
        hexd, name = line.split(" *")
        assert sha(os.path.join(out, name)) == hexd, name
    rec = json.load(open(os.path.join(out, "vid00000001.video.json"), encoding="utf-8"))
    assert [c["at"] for c in rec["chapters"]] == ["00:00:00", "00:01:51"]
    assert rec["media"]["file"] == "vid00000001.mp4" and "research copy" in rec["media"]["note"]
    assert "googlevideo" not in json.dumps(rec), "a stream address carries the viewer's IP and is not kept"
    source = open(os.path.join(out, "SOURCE.txt"), encoding="utf-8").read()
    assert "local research copy" in source and "3 comments with replies" in source
    assert res.balance["counts"]["comments"] == 3


def test_a_cmmns_thread_file_reads_into_the_synthesis():
    doc = {"format": "cmmns.capture-thread/2", "post": {"url": "u"}, "comments": [
        {"id": "A", "text": "t", "score": 4, "flair": "channel owner", "replies": [{"id": "A.1", "text": "r", "score": "1.2K", "replies": []}]}]}
    flat, _, url = comments_from_file(doc)
    assert url == "u"
    assert flat[0]["author_is_uploader"] is True and flat[0]["like_count"] == 4
    assert flat[1]["parent"] == "A" and flat[1]["like_count"] == 0


class MediaFake(FakeYtDlp):
    """The scripted yt-dlp, plus the media download from the saved info."""

    def __call__(self, argv, timeout):
        if "--load-info-json" in argv and "-f" in argv:
            self.calls.append(list(argv))
            out = argv[argv.index("-o") + 1].replace("%(id)s.%(ext)s", "vid00000001.mp4")
            open(out, "wb").write(b"video bytes")
            return CallResult(0, "", "")
        return super().__call__(argv, timeout)


def source(fake):
    return VideoSource(runner=fake, with_comments=True, which=lambda n: None, sleep=lambda s: None,
                       log=lambda m: None, clock=lambda: 1.0, extractor_args=("youtube:max_comments=600,all,all,all;comment_sort=top",))


def test_the_live_bundle_reads_comments_with_a_cap_and_skips_media_unless_asked(tmp_path):
    fake = MediaFake({"vid00000001": video_info("vid00000001", comments=3)})
    res = fetch_bundle("https://www.youtube.com/watch?v=vid00000001", str(tmp_path / "b"), source(fake))
    assert res.ok and res.comments == 3 and res.media is None
    extract = fake.calls[0]
    assert "--write-comments" in extract and "youtube:max_comments=600,all,all,all;comment_sort=top" in extract
    assert extract[-2] == "--"
    assert not any("-f" in c for c in fake.calls), "no media call when the media file was not asked for"
    assert "vid00000001.transcript.txt" in res.files


def test_the_media_file_is_saved_when_asked_and_listed_in_the_hashes(tmp_path):
    fake = MediaFake({"vid00000001": video_info("vid00000001", comments=1)})
    res = fetch_bundle("https://www.youtube.com/watch?v=vid00000001", str(tmp_path / "b"), source(fake), media=True)
    assert res.media == "vid00000001.mp4"
    assert any(line.rstrip().endswith("*vid00000001.mp4") for line in open(tmp_path / "b" / "SHA256SUMS", encoding="utf-8"))


def test_a_bot_check_stops_the_bundle_before_anything_is_written(tmp_path):
    fake = MediaFake({"vid00000001": video_info("vid00000001")})
    fake.unplayable["vid00000001"] = (BOT_CHECK, -1)
    res = fetch_bundle("https://www.youtube.com/watch?v=vid00000001", str(tmp_path / "b"), source(fake), media=True)
    assert not res.ok and "bot check" in res.error
    assert not (tmp_path / "b").exists()
    assert len(fake.calls) == 1
