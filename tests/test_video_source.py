import pytest
from fake_ytdlp import FakeYtDlp, asr, video_info

from gather.pacing import BackoffPolicy
from gather.video import VideoSource as ReExported
from gather.video_source import VideoSource

FAST = BackoffPolicy(base=1, factor=2, cap=10, max_attempts=3, max_total_wait=100, jitter=0)
URL = "https://www.youtube.com/watch?v=abc"


def make(fake, *, captions="with", comments=False, which=lambda n: "/bin/node", backoff=FAST, **kw):
    logs, slept = [], []
    src = VideoSource(runner=fake, captions=captions, with_comments=comments, which=which,
                      backoff=backoff, sleep=slept.append, rand=lambda: 0.5, log=logs.append,
                      clock=lambda: 1.0, **kw)
    return src, logs, slept


def test_old_import_path_still_works():
    assert ReExported is VideoSource


def test_every_call_uses_node_when_it_is_on_path():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake)
    src.fetch(URL)
    assert fake.calls and all(c[1:3] == ["--js-runtimes", "node"] for c in fake.calls)


def test_js_runtime_can_be_turned_off():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, js_runtime="none")
    src.fetch(URL)
    assert all("--js-runtimes" not in c for c in fake.calls)


def test_pacing_flags_reach_yt_dlp():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, sleep_requests=1, sleep_subtitles=15)
    src.fetch(URL)
    assert all(c[3:7] == ["--sleep-requests", "1", "--sleep-subtitles", "15"] for c in fake.calls)


def test_full_pass_downloads_exactly_one_track_and_stamps_auto_caption():
    info = video_info("abc", auto=("en-orig", "ar-orig"))
    info["automatic_captions"]["en"] = asr("ar", tlang="en")    # a translation that must not be fetched
    fake = FakeYtDlp({"abc": info})
    src, _, _ = make(fake, comments=True)
    out = src.gather(URL)
    caption_calls = [c for c in fake.calls if "--load-info-json" in c]
    assert len(caption_calls) == 1 and "--write-auto-subs" in caption_calls[0]
    assert out.caption == "auto" and out.caption_lang == "en-orig"
    tr = next(i for i in out.items if i.kind == "transcript")
    assert tr.provenance.method == "auto-caption" and tr.text == "hello from abc"
    assert out.comments == 2 and {i.kind for i in out.items} == {"metadata", "transcript", "comment"}


def test_manual_track_is_fetched_with_write_subs_and_stamped_yt_dlp():
    fake = FakeYtDlp({"abc": video_info("abc", manual=("en",))})
    src, _, _ = make(fake)
    out = src.gather(URL)
    assert out.caption == "manual"
    assert "--write-subs" in next(c for c in fake.calls if "--load-info-json" in c)
    assert next(i for i in out.items if i.kind == "transcript").provenance.method == "yt-dlp"


def test_no_captions_pass_never_touches_the_caption_endpoint():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, captions="skip", comments=True)
    out = src.gather(URL)
    assert len(fake.calls) == 1 and "--write-comments" in fake.calls[0]
    assert out.caption == "skipped" and {i.kind for i in out.items} == {"metadata", "comment"}


def test_captions_only_pass_keeps_only_the_transcript_and_skips_comments():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, captions="only", comments=True)
    out = src.gather(URL)
    assert "--write-comments" not in fake.calls[0]
    assert [i.kind for i in out.items] == ["transcript"]


def test_missing_captions_carry_a_reason_and_make_no_caption_request():
    fake = FakeYtDlp({"abc": video_info("abc", auto=())})
    src, _, _ = make(fake)
    out = src.gather(URL)
    assert out.caption == "missing" and out.caption_reason == "none-offered"
    assert not any("--load-info-json" in c for c in fake.calls)


def test_a_429_is_retried_with_backoff_and_every_retry_is_logged():
    fake = FakeYtDlp({"abc": video_info("abc")})
    fake.throttle["captions"] = 2
    src, logs, slept = make(fake)
    out = src.gather(URL)
    assert out.caption == "auto" and not out.throttled
    assert slept == [1, 2]
    assert [a["attempt"] for a in out.attempts] == [2, 3]
    assert sum("throttled" in m for m in logs) == 2


def test_exhausted_backoff_marks_captions_missing_as_rate_limited():
    fake = FakeYtDlp({"abc": video_info("abc")})
    fake.throttle["captions"] = -1
    src, logs, _ = make(fake)
    out = src.gather(URL)
    assert out.ok and out.throttled
    assert out.caption == "missing" and out.caption_reason == "rate-limited"
    assert "HTTP Error 429" in out.caption_detail and "older than 90 days" not in out.caption_detail
    assert out.attempts[-1]["final"] is True
    assert any("backoff budget spent" in m for m in logs)
    assert [i.kind for i in out.items] == ["metadata"]   # metadata survives a caption failure


def test_metadata_failure_reports_the_error_line_not_the_version_warning():
    fake = FakeYtDlp({})
    fake.fail["abc"] = ("WARNING: [youtube] Your yt-dlp version is older than 90 days\n"
                        "ERROR: [youtube] abc: Video unavailable. This video is private\n")
    src, _, _ = make(fake)
    with pytest.raises(RuntimeError, match="ERROR: \\[youtube\\] abc: Video unavailable"):
        src.fetch(URL)
    out = src.gather(URL)
    assert out.error_code == "unavailable" and out.caption_reason == "unavailable"


def test_unknown_caption_mode_is_rejected():
    with pytest.raises(ValueError):
        VideoSource(captions="sometimes")


def test_run_config_video_jobs_can_pick_a_pass():
    from gather.run_config import build_source
    fake = FakeYtDlp({"abc": video_info("abc")})
    src = build_source("video", {"comments": True, "captions": "skip"})
    src._runner = fake
    kinds = {i.kind for i in src.fetch(URL)}
    assert kinds == {"metadata", "comment"} and not any("--load-info-json" in c for c in fake.calls)
