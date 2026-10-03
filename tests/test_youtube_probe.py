"""The yt-dlp throttle probe: fixed videos, a single user's pace, measured rates and a verdict."""
import pytest
from fake_ytdlp import BOT_CHECK, WARN, FakeYtDlp, video_info

from gather.pacing import BackoffPolicy
from gather.video_source import VideoSource
from gather.youtube_probe import MIN_GAP_S, PROBE_VIDEOS, run_probe, verdict
from gather.youtube_route import TimedRunner

FAST = BackoffPolicy(base=1, factor=2, cap=10, max_attempts=2, max_total_wait=10, jitter=0)


class Tick:
    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def probe(fake, step=1.0, gap=MIN_GAP_S):
    timed = TimedRunner(fake, Tick(step))
    src = VideoSource(runner=timed, backoff=FAST, sleep=lambda s: None, rand=lambda: 0.5,
                      log=lambda m: None, which=lambda n: None, clock=lambda: 1.0)
    slept = []
    return run_probe(timed, src.gather, gap_s=gap, sleep=slept.append), slept


def healthy():
    return FakeYtDlp({v: video_info(v) for v in PROBE_VIDEOS})


def test_a_healthy_path_is_ok_and_measured():
    report, slept = probe(healthy())
    assert report["verdict"] == "ok" and [r["video"] for r in report["videos"]] == list(PROBE_VIDEOS)
    assert slept == [MIN_GAP_S, MIN_GAP_S], "one pause between each pair of videos"
    row = report["videos"][0]
    assert row["metadata_s"] == 1.0 and row["metadata_calls"] == 1 and row["caption"] == "auto"
    assert row["caption_bytes"] > 0 and row["caption_bytes_per_s"] == float(row["caption_bytes"])
    assert report["median_metadata_s"] == 1.0 and report["metadata_calls_per_min"] == 60.0


def test_the_probe_sends_at_most_two_requests_per_video():
    fake = healthy()
    probe(fake)
    assert len(fake.calls) == 2 * len(PROBE_VIDEOS)


def test_a_rate_limit_makes_the_verdict_throttled():
    fake = healthy()
    fake.throttle["metadata"] = -1
    report, _ = probe(fake)
    assert report["verdict"] == "throttled"


def test_a_bot_check_makes_the_verdict_throttled():
    fake = healthy()
    fake.unplayable[PROBE_VIDEOS[1]] = (BOT_CHECK, -1)
    assert probe(fake)[0]["verdict"] == "throttled"


def test_a_bot_check_on_the_caption_download_makes_the_verdict_throttled():
    fake = healthy()
    fake.caption_fail = WARN + f"ERROR: [youtube] x: {BOT_CHECK}" + chr(10)
    report, _ = probe(fake)
    assert all(r["ok"] for r in report["videos"]) and report["verdict"] == "throttled"


def test_slow_metadata_calls_make_the_verdict_throttled():
    report, _ = probe(healthy(), step=25.0)
    assert report["verdict"] == "throttled" and "median metadata call" in report["reason"]


def test_every_video_failing_otherwise_is_failing():
    fake = healthy()
    for v in PROBE_VIDEOS:
        fake.fail[v] = "ERROR: could not run yt-dlp: not found\n"
    assert probe(fake)[0]["verdict"] == "failing"


def test_the_gap_cannot_go_below_the_floor():
    with pytest.raises(ValueError):
        probe(healthy(), gap=0.5)


def test_verdict_on_no_rows_is_ok_but_says_so():
    assert verdict([])[0] == "ok"
