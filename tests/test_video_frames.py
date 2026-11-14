"""Contact sheets from storyboard sprite images: the cut, the sheet layout, the table, the bundle's
record, --no-frames, a refusal that is never retried, the same bytes on a second run, and the fast
path that reads captions and frames while yt-dlp is still reading comments. No test calls the
network: the sprite images are made here and handed in through a fake fetcher."""

import io
import json
import os
import threading

import pytest
from fake_ytdlp import FakeYtDlp, video_info
from test_storyboard import sb

from gather.cli import main
from gather.pacing import HostLimiter
from gather.storyboard import best_level, plan_frames
from gather.video_bundle_run import _early_info, fetch_bundle
from gather.video_frames import NONE_OFFERED, SKIPPED, fetch_frames, frame_record
from gather.video_source import VideoSource

Image = pytest.importorskip("PIL.Image")

URL = "https://www.youtube.com/watch?v=vid00000001"
W, H = 32, 18


def colour(index):
    return (index * 37 % 256, index * 91 % 256, index * 53 % 256)


def sprite(fragment, rows=3, columns=3, frames=9, w=W):
    """A sprite image whose every thumbnail is one flat colour named by its frame number."""
    img = Image.new("RGB", (columns * w, rows * H), (0, 0, 0))
    for k in range(frames):
        img.paste(colour(fragment * 9 + k), (k % columns * w, k // columns * H, k % columns * w + w, k // columns * H + H))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def board(fragments=14, last=2):
    return sb("sb0", W, H, 3, 3, fragments, last=last)


class Fetcher:
    def __init__(self, refuse_at=None, status=429):
        self.urls, self.refuse_at, self.status = [], refuse_at, status

    def __call__(self, url):
        self.urls.append(url)
        if self.refuse_at is not None and len(self.urls) > self.refuse_at:
            return self.status, b""
        return 200, sprite(int(url.split("/M")[1].split(".")[0]))


def no_wait():
    return HostLimiter(1.0, clock=lambda: 0.0, sleep=lambda s: None)


def source(fake):
    return VideoSource(runner=fake, with_comments=True, which=lambda n: None, sleep=lambda s: None,
                       log=lambda m: None, clock=lambda: 1.0)


def with_board(**kw):
    doc = video_info("vid00000001", comments=2)
    doc["formats"].append(board(**kw))
    return {"vid00000001": doc}


def bundle(tmp_path, name="b", fetcher=None, **kw):
    fetcher = fetcher or Fetcher()
    res = fetch_bundle(URL, str(tmp_path / name), source(kw.pop("fake", None) or FakeYtDlp(with_board())),
                       fetcher=fetcher, limiter=no_wait(), **kw)
    rec = json.load(open(tmp_path / name / "vid00000001.video.json", encoding="utf-8")) if res.ok else None
    return res, rec, fetcher


def test_the_cut_puts_each_frame_in_its_cell_with_its_time_in_the_table(tmp_path):
    level = best_level({"duration": 238, "formats": [board()]})
    got = fetch_frames({"duration": 238, "formats": [board()]}, fetcher=Fetcher(), limiter=no_wait())
    rec = frame_record(str(tmp_path), "vid", got)
    assert rec["status"] == "ok" and rec["count"] == 96 and rec["missing"] == 0 and rec["available"] == 119
    assert rec["sheets"] == [f"vid.frames-0{n}.jpg" for n in (1, 2, 3, 4)], "24 frames to a sheet"
    assert rec["cell_px"] == [320, 180] and rec["sheet_px"] == [6 * 320 + 7 * 8, 4 * 180 + 5 * 8]
    rows = [ln.split("\t") for ln in open(tmp_path / "vid.frames.tsv", encoding="utf-8").read().splitlines()]
    assert rows[0] == ["time_s", "time", "sheet", "row", "column", "x", "y", "width", "height", "frame"]
    assert len(rows) == 97
    plan = plan_frames(level)
    assert [int(r[9]) for r in rows[1:]] == [f.index for f in plan]
    assert rows[1][:5] == ["0.000", "00:00:00", "vid.frames-01.jpg", "1", "1"]
    assert rows[7][2:7] == ["vid.frames-01.jpg", "2", "1", "8", "196"], "six to a row"
    assert rows[25][2:5] == ["vid.frames-02.jpg", "1", "1"]
    assert rows[-1][0] == "236.000" and rows[-1][1] == "00:03:56"
    for row in (rows[1], rows[30], rows[96]):
        sheet = Image.open(tmp_path / row[2])
        assert sheet.size[0] == 1976
        got_px = sheet.getpixel((int(row[5]) + 160, int(row[6]) + 60))
        assert all(abs(a - b) <= 12 for a, b in zip(got_px, colour(int(row[9])))), (row, got_px)
        label = sheet.getpixel((int(row[5]) + 2, int(row[6]) + 178))
        assert max(label) < 40, "the time is printed on a dark box at the foot of the frame"


def test_a_sprite_narrower_than_its_declared_size_and_a_short_last_sprite_still_give_every_frame(tmp_path):
    """YouTube declares 318 pixel thumbnails for a 951 pixel row of three, and the last sprite
    image holds only the frames that are left."""
    doc = {"duration": 13, "formats": [board(fragments=2, last=4)]}

    def narrow(url):
        n = int(url.split("/M")[1].split(".")[0])
        return 200, sprite(n, w=W - 1) if n == 0 else sprite(n, rows=2, columns=3, frames=4, w=W - 1)

    rec = frame_record(str(tmp_path), "vid", fetch_frames(doc, fetcher=narrow, limiter=no_wait()))
    assert rec["status"] == "ok" and rec["count"] == 13 and rec["missing"] == 0
    rows = [ln.split("\t") for ln in open(tmp_path / "vid.frames.tsv", encoding="utf-8").read().splitlines()][1:]
    sheet = Image.open(tmp_path / "vid.frames-01.jpg")
    for row in (rows[2], rows[8], rows[12]):
        got_px = sheet.getpixel((int(row[5]) + 160, int(row[6]) + 60))
        assert all(abs(a - b) <= 12 for a, b in zip(got_px, colour(int(row[9])))), (row, got_px)


def test_the_bundle_record_says_what_the_frames_are_and_hashes_the_sheets(tmp_path):
    res, rec, fetcher = bundle(tmp_path)
    frames = rec["frames"]
    assert frames["source"] == "site preview storyboard" and frames["level"] == "sb0"
    assert frames["frame_px"] == [W, H], "the real thumbnail size, not the size it is drawn at"
    assert "32 by 18 pixels" in frames["note"] and "not full-resolution" in frames["note"]
    assert frames["count"] == 96 and frames["sprite_images"] == 14 and frames["interval_s"] == 2.0
    assert len(fetcher.urls) == 14 and len(set(fetcher.urls)) == 14, "each sprite image is asked for once"
    sums = open(tmp_path / "b" / "SHA256SUMS", encoding="utf-8").read()
    for name in (*frames["sheets"], frames["table"]):
        assert f"*{name}" in sums and name in res.files
    assert "i.ytimg.com" not in json.dumps(rec), "no storyboard address is kept"
    assert "96 frames on 4 contact sheets" in res.frames
    assert "96 frames on 4 contact sheets" in open(tmp_path / "b" / "SOURCE.txt", encoding="utf-8").read()
    assert set(res.timings) >= {"extract_s", "captions_s", "frames_fetch_s", "write_s", "total_s"}


def test_no_frames_asks_for_nothing_and_says_so(tmp_path):
    res, rec, fetcher = bundle(tmp_path, frames=False)
    assert rec["frames"] == SKIPPED and fetcher.urls == []
    assert not [f for f in os.listdir(tmp_path / "b") if "frames" in f]


def test_a_video_without_a_storyboard_records_none_offered(tmp_path):
    fake = FakeYtDlp({"vid00000001": video_info("vid00000001")})
    res, rec, fetcher = bundle(tmp_path, fake=fake)
    assert rec["frames"] == NONE_OFFERED == "none offered" and fetcher.urls == []
    assert res.frames == "frames: none offered"


def test_a_refusal_stops_the_frame_stage_and_is_never_asked_again(tmp_path):
    res, rec, fetcher = bundle(tmp_path, fetcher=Fetcher(refuse_at=0))
    assert res.ok, "the rest of the bundle is still written"
    assert rec["frames"].startswith("not fetched: sprite image 1 of 14: HTTP 429") and len(fetcher.urls) == 1
    res, rec, fetcher = bundle(tmp_path, "c", fetcher=Fetcher(refuse_at=5, status=403))
    assert len(fetcher.urls) == 6, "five sprite images, one refusal, no retry"
    frames = rec["frames"]
    assert frames["status"] == "partial" and "HTTP 403" in frames["error"]
    assert frames["count"] + frames["missing"] == 96 and frames["sprite_images"] == 5 and 0 < frames["count"] < 96


def test_the_same_inputs_give_the_same_bytes_on_a_second_run(tmp_path):
    _, rec1, _ = bundle(tmp_path, "one")
    _, rec2, _ = bundle(tmp_path, "two")
    assert rec1["frames"] == rec2["frames"]
    for name in (*rec1["frames"]["sheets"], rec1["frames"]["table"]):
        assert open(tmp_path / "one" / name, "rb").read() == open(tmp_path / "two" / name, "rb").read(), name


class EarlyFake(FakeYtDlp):
    """yt-dlp that writes its info to the --print-to-file path once the page is read, then keeps
    reading comments until the caption download has been made."""

    def __init__(self, videos):
        super().__init__(videos)
        self.captions_done, self.saw_captions_during_comments = threading.Event(), False

    def __call__(self, argv, timeout):
        if "--print-to-file" not in argv:
            res = super().__call__(argv, timeout)
            if "--load-info-json" in argv:
                self.captions_done.set()
            return res
        self.calls.append(list(argv))
        at = argv.index("--print-to-file")
        assert argv[at + 1] == "pre_process:%()j"
        early = {k: v for k, v in self.videos["vid00000001"].items() if k != "_comments"}
        with open(argv[at + 2], "w", encoding="utf-8") as f:
            f.write(json.dumps({**early, "__post_extractor": "<function>"}) + "\n")
        self.saw_captions_during_comments = self.captions_done.wait(10)
        return self._extract(argv)


def test_fast_reads_captions_and_frames_while_the_comments_are_still_being_read(tmp_path):
    fake = EarlyFake(with_board())
    res, rec, fetcher = bundle(tmp_path, fake=fake, fast=True)
    assert fake.saw_captions_during_comments, "the caption download ran before the extraction call returned"
    assert res.ok and res.comments == 2 and res.caption == "auto" and rec["frames"]["count"] == 96
    assert sum("--dump-single-json" in c for c in fake.calls) == 1, "one extraction serves everything"
    assert "__post_extractor" not in fake.caption_infos[0], "yt-dlp's working state is not handed back to it"
    assert "metadata_s" in res.timings


def test_fast_falls_back_to_the_finished_info_when_no_early_info_is_written(tmp_path):
    fake = FakeYtDlp(with_board())
    res, rec, _ = bundle(tmp_path, fake=fake, fast=True)
    assert res.ok and rec["frames"]["count"] == 96 and "metadata_s" not in res.timings
    assert "--print-to-file" in fake.calls[0]


def test_early_info_waits_for_a_whole_line(tmp_path):
    class Ended:
        def done(self):
            return True

    path = tmp_path / "early.json"
    assert _early_info(str(path), Ended()) is None
    path.write_text('{"id": "half', encoding="utf-8")
    assert _early_info(str(path), Ended()) is None
    path.write_text('{"id": "v", "__x": 1}\n{"id": "second attempt"}\n', encoding="utf-8")
    assert _early_info(str(path), Ended()) == {"id": "v"}


def test_the_command_takes_fast_and_no_frames(tmp_path, monkeypatch, capsys):
    import gather.video_bundle_cmd as cmd
    seen = {}

    def fake_fetch(url, out, src, **kw):
        from gather.video_bundle_run import BundleResult
        seen.update(kw, argv=src.base_argv, extractor=src._extractor_args)
        return BundleResult(out_dir=out, video_id="v")

    monkeypatch.setattr("gather.video_bundle_run.fetch_bundle", fake_fetch)
    assert main(["video-bundle", URL, "--out", str(tmp_path / "o"), "--fast", "--no-frames", "--max-comments", "300", "--json"]) == 0
    assert seen["fast"] is True and seen["frames"] is False
    assert seen["argv"][seen["argv"].index("--sleep-requests") + 1] == "1"
    assert seen["extractor"] == ("youtube:max_comments=300,all,30,5;comment_sort=top",)
    assert seen["limiter"].spacing == 1.0
    assert main(["video-bundle", URL, "--out", str(tmp_path / "o"), "--fast", "--sleep-requests", "4"]) == 0
    assert seen["argv"][seen["argv"].index("--sleep-requests") + 1] == "4" and seen["frames"] is True
    assert seen["limiter"].spacing == 4.0
    assert main(["video-bundle", URL, "--out", str(tmp_path / "o"), "--max-replies", "-1"]) == 2
    assert cmd.FAST_SPACING == 1.0
    capsys.readouterr()
