import pytest
from fake_ytdlp import (
    BOT_CHECK,
    GEO,
    PRIVATE,
    REMOVED,
    SESSION_LIMIT,
    UPCOMING,
    FakeYtDlp,
    asr,
    video_info,
)

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
    assert fake.calls and all(c[:4] == ["yt-dlp", "--ignore-config", "--js-runtimes", "node"]
                              for c in fake.calls)


def test_js_runtime_can_be_turned_off():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, js_runtime="none")
    src.fetch(URL)
    assert all("--js-runtimes" not in c for c in fake.calls)


def test_pacing_flags_reach_yt_dlp():
    fake = FakeYtDlp({"abc": video_info("abc")})
    src, _, _ = make(fake, sleep_requests=1, sleep_subtitles=15)
    src.fetch(URL)
    assert all(c[1] == "--ignore-config" and c[4:8] == ["--sleep-requests", "1", "--sleep-subtitles", "15"]
               for c in fake.calls)


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


def _keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


def test_the_caption_download_does_not_ask_yt_dlp_to_pose_as_a_browser():
    # yt-dlp marks every YouTube caption track "impersonate": true and keeps the mark in -J.
    # Handed back through --load-info-json, the mark makes yt-dlp download the track with a
    # browser's TLS fingerprint and headers whenever curl_cffi is importable where it runs.
    info = video_info("abc", manual=("en",))
    assert info["subtitles"]["en"][0]["impersonate"] is True
    fake = FakeYtDlp({"abc": info})
    src, _, _ = make(fake)
    out = src.gather(URL)
    assert out.caption == "manual" and len(fake.caption_infos) == 1
    assert "impersonate" not in set(_keys(fake.caption_infos[0]))
    assert fake.caption_infos[0]["subtitles"]["en"][0]["url"] == "https://x/en"   # the track itself is kept


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


def _metadata_calls(fake):
    return [c for c in fake.calls if "--load-info-json" not in c]


@pytest.mark.parametrize("reason,code", [(BOT_CHECK, "bot-check"), (SESSION_LIMIT, "rate-limited")],
                         ids=["bot-check", "session-limit"])
def test_a_throttle_warning_on_a_zero_exit_is_retried_then_marked_throttled(reason, code):
    fake = FakeYtDlp({"abc": video_info("abc")})
    fake.unplayable["abc"] = (reason, -1)
    src, logs, slept = make(fake)
    out = src.gather(URL)
    assert not out.ok and out.error_code == code and out.throttled
    assert out.error.startswith("yt-dlp failed: served no formats: WARNING: [youtube] ")
    assert len(_metadata_calls(fake)) == 3 and slept == [1, 2]     # two retries, then the budget is spent
    assert out.attempts[-1]["final"] is True and out.attempts[-1]["step"] == "metadata"
    assert out.items == [] and out.caption == "missing" and out.caption_reason == code
    assert not any("--load-info-json" in c for c in fake.calls)    # never asks for a track it was not shown
    assert any("backoff budget spent" in m for m in logs)


def test_a_bot_check_that_clears_is_gathered_on_the_retry():
    fake = FakeYtDlp({"abc": video_info("abc")})
    fake.unplayable["abc"] = (BOT_CHECK, 1)
    src, _, slept = make(fake)
    out = src.gather(URL)
    assert out.ok and not out.throttled and slept == [1]
    assert out.caption == "auto" and {i.kind for i in out.items} == {"metadata", "transcript"}
    assert out.attempts[0]["reason"].startswith("bot-check: served no formats")


@pytest.mark.parametrize("reason,code", [(PRIVATE, "private"), (REMOVED, "unavailable"),
                                         (GEO, "geo-blocked"), (UPCOMING, "upcoming")],
                         ids=["private", "removed", "geo", "upcoming"])
def test_a_playability_warning_that_is_not_a_throttle_fails_without_a_retry(reason, code):
    fake = FakeYtDlp({"abc": video_info("abc")})
    fake.unplayable["abc"] = (reason, -1)
    src, _, slept = make(fake, captions="skip")
    with pytest.raises(RuntimeError, match="served no formats"):
        src.fetch(URL)
    out = src.gather(URL)
    assert out.error_code == code and not out.throttled and out.items == []   # no degraded metadata item
    assert slept == [] and len(fake.calls) == 2                              # one call per gather


def test_a_video_that_lists_no_formats_for_no_stated_reason_keeps_its_captions():
    fake = FakeYtDlp({"abc": video_info("abc", formats=False)})
    src, _, _ = make(fake)
    out = src.gather(URL)
    assert out.ok and out.caption == "auto" and not out.attempts
    assert "--ignore-no-formats-error" in fake.calls[0]


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
