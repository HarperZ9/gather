import json
import sys

import fake_ytdlp
import pytest
from fake_ytdlp import (
    BOT_CHECK,
    GEO,
    NO_FORMATS,
    PRIVATE,
    REMOVED,
    SESSION_LIMIT,
    UPCOMING,
)

import gather.ytdlp as ytdlp_mod
from gather.spawn import ToolRefused
from gather.ytdlp import (
    CallResult,
    YtDlpConfig,
    base_argv,
    check_playability,
    classify,
    failure_reason,
    playability_warning,
    resolve_js_runtime,
    subprocess_runner,
    throttle_reason,
)


def on_path(name):
    return f"/usr/bin/{name}"


def not_on_path(name):
    return None


def test_auto_runtime_uses_node_only_when_it_is_on_path():
    assert resolve_js_runtime("auto", on_path) == "node"
    assert resolve_js_runtime("auto", not_on_path) is None


@pytest.mark.parametrize("setting", [None, "", "none", "NONE"])
def test_runtime_can_be_disabled(setting):
    assert resolve_js_runtime(setting, on_path) is None


def test_explicit_runtime_passes_through():
    assert resolve_js_runtime("deno", not_on_path) == "deno"
    assert resolve_js_runtime("node:/opt/node/bin", not_on_path) == "node:/opt/node/bin"


def test_base_argv_carries_runtime_and_pacing_flags():
    cfg = YtDlpConfig(binary="yt-dlp", js_runtime="auto", sleep_requests=1.5, sleep_subtitles=20)
    assert base_argv(cfg, on_path) == ["yt-dlp", "--ignore-config", "--js-runtimes", "node",
                                       "--sleep-requests", "1.5", "--sleep-subtitles", "20"]
    assert base_argv(YtDlpConfig(js_runtime="auto"), not_on_path) == ["yt-dlp", "--ignore-config"]


STDERR_429 = (
    "WARNING: [youtube] Your yt-dlp version (2026.08.19) is older than 90 days\n"
    "WARNING: [youtube] No supported JavaScript runtime could be found\n"
    "[info] abc: Downloading subtitles: en-orig\n"
    "ERROR: Unable to download video subtitles for 'en-orig': HTTP Error 429: Too Many Requests\n"
)


def test_failure_reason_reports_the_error_line_not_the_leading_warning():
    reason = failure_reason(STDERR_429)
    assert reason.startswith("ERROR: Unable to download video subtitles")
    assert "older than 90 days" not in reason


def test_failure_reason_joins_several_error_lines():
    assert failure_reason("ERROR: one\nWARNING: w\nERROR: two\n") == "ERROR: one | ERROR: two"


def test_failure_reason_falls_back_to_the_last_non_warning_line():
    assert failure_reason("WARNING: a\nTraceback: boom\nWARNING: b\n") == "Traceback: boom"
    assert failure_reason("WARNING: only a warning\n") == "WARNING: only a warning"
    assert failure_reason("") == "no error output"


@pytest.mark.parametrize("text,code", [
    ("ERROR: ... HTTP Error 429: Too Many Requests", "rate-limited"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot", "bot-check"),
    ("ERROR: [youtube] x: Sign in to confirm your age", "age-restricted"),
    ("ERROR: [youtube] x: Join this channel to get access to members-only content", "members-only"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader", "unavailable"),
    ("ERROR: [youtube] x: Premieres in 3 hours", "upcoming"),
    ("ERROR: [youtube] x: Requested format is not available", "no-formats"),
    ("ERROR: something new", "error"),
])
def test_classify_names_the_failure(text, code):
    assert classify(text) == code


def test_a_warning_cannot_make_a_transient_failure_terminal():
    # "not available" in a WARNING must not classify the call as an unavailable video
    res = CallResult(1, "", "WARNING: some formats are not available\nERROR: HTTP Error 429: Too Many Requests\n")
    assert res.code() == "rate-limited"


def test_throttle_reason_only_for_throttle_codes():
    assert throttle_reason(CallResult(1, "", STDERR_429)).startswith("rate-limited: ERROR")
    assert throttle_reason(CallResult(1, "", "ERROR: Video unavailable")) is None
    assert throttle_reason(CallResult(0, "{}", STDERR_429)) is None   # a success is never retried


def test_runner_reports_a_missing_binary_as_a_failed_call():
    res = subprocess_runner(["gather-no-such-binary-xyz"], 5)
    assert not res.ok and res.returncode == 127
    assert res.code() == "tool-missing" and res.reason().startswith("ERROR: could not run")


def test_runner_reports_a_timeout_as_a_failed_call():
    res = subprocess_runner([sys.executable, "-c", "import time; time.sleep(5)"], 0.5)
    assert res.timed_out and not res.ok and res.code() == "timeout"
    assert res.reason() == "timed out after 0.5s"


def test_runner_decodes_output_as_utf8():
    res = subprocess_runner([sys.executable, "-c", "import sys; sys.stdout.buffer.write('Rosić'.encode())"], 10)
    assert res.ok and res.stdout == "Rosić"


def test_runner_reports_a_refused_start_as_a_failed_call_that_is_not_retried(monkeypatch):
    seen = []

    def refuse(name, args, **kw):
        seen.append((name, list(args), kw))
        raise ToolRefused("UNSAFE_ARGUMENT", "a batch-file target was refused")

    monkeypatch.setattr(ytdlp_mod, "run_tool", refuse)
    res = subprocess_runner(["yt-dlp", "--ignore-config", "-o", "%(id)s.%(ext)s"], 5)
    assert seen == [("yt-dlp", ["--ignore-config", "-o", "%(id)s.%(ext)s"], {"timeout": 5, "network": True})]
    assert not res.ok and res.returncode == 126 and res.code() == "tool-refused"
    assert res.reason().startswith("ERROR: refused to run yt-dlp (UNSAFE_ARGUMENT)")
    assert throttle_reason(res) is None   # a refusal will not change on a retry


def test_runner_names_the_program_as_given_never_a_resolved_path(tmp_path):
    missing = str(tmp_path / "tools" / "yt-dlp")
    res = subprocess_runner([missing], 5)
    assert res.code() == "tool-missing" and str(tmp_path) not in res.reason()


# --- playability: what yt-dlp says, with --ignore-no-formats-error, when a video serves nothing ----

def test_youtubes_session_rate_limit_is_a_throttle_not_an_unavailable_video():
    # yt-dlp 2026.08.19 prefixes YouTube's own "Video unavailable" to the session limit
    for prefix in ("ERROR: [youtube] abc: ", "WARNING: [youtube] "):
        assert classify(prefix + SESSION_LIMIT) == "rate-limited"
    assert throttle_reason(CallResult(1, "", f"ERROR: [youtube] abc: {SESSION_LIMIT}\n")).startswith("rate-limited")
    assert classify("ERROR: [youtube] abc: " + REMOVED) == "unavailable"   # a removed video stays terminal


def _page(formats=()):
    return json.dumps({"id": "abc", "title": "T", "formats": list(formats), "automatic_captions": {}})


def _warned(reason):
    return f"{fake_ytdlp.WARN}WARNING: [youtube] {reason}\n{NO_FORMATS}"


@pytest.mark.parametrize("reason,code,throttle", [
    (BOT_CHECK, "bot-check", True),
    (SESSION_LIMIT, "rate-limited", True),
    (PRIVATE, "private", False),
    (REMOVED, "unavailable", False),
    (GEO, "geo-blocked", False),
    (UPCOMING, "upcoming", False),
], ids=["bot-check", "session-limit", "private", "removed", "geo", "upcoming"])
def test_a_zero_exit_that_served_no_formats_fails_with_its_playability_reason(reason, code, throttle):
    res = check_playability(CallResult(0, _page(), _warned(reason)))
    assert res.returncode == 0 and not res.ok and res.code() == code
    assert res.reason().startswith("served no formats: WARNING: [youtube] ")
    assert (throttle_reason(res) is not None) is throttle
    assert "older than 90 days" not in res.reason()


def test_no_formats_without_a_playability_reason_stays_a_success():
    # a video YouTube serves only through a client yt-dlp skipped still has metadata and captions
    res = CallResult(0, _page(), fake_ytdlp.WARN + NO_FORMATS)
    assert check_playability(res) is res and res.ok


def test_a_throttle_warning_on_a_call_that_still_served_formats_stays_a_success():
    stderr = "WARNING: [youtube] abc: Unable to download webpage: HTTP Error 429: Too Many Requests\n"
    res = CallResult(0, _page([{"format_id": "18", "url": "https://x/v.mp4"}]), stderr)
    assert check_playability(res) is res and res.ok


def test_only_extractor_warnings_are_read_as_playability():
    # yt-dlp's own no-formats lines and a version warning never name a reason
    assert playability_warning(fake_ytdlp.WARN + NO_FORMATS) is None
    assert playability_warning("[youtube] abc: Private video\n") is None     # not a warning line
    assert playability_warning(_warned(PRIVATE)).startswith("WARNING: [youtube] Private video.")


def test_a_throttle_line_wins_over_a_terminal_line():
    stderr = f"WARNING: [youtube] {PRIVATE}\nWARNING: [youtube] {BOT_CHECK}\n{NO_FORMATS}"
    assert classify(playability_warning(stderr)) == "bot-check"


def test_a_failed_or_unreadable_call_is_left_as_it_is():
    failed = CallResult(1, "", f"ERROR: [youtube] abc: {BOT_CHECK}\n")
    assert check_playability(failed) is failed
    garbled = CallResult(0, "not json", _warned(BOT_CHECK))   # the caller's JSON check reports it
    assert check_playability(garbled) is garbled


def test_a_replacement_character_for_the_curly_apostrophe_still_reads_as_a_bot_check():
    # on Windows yt-dlp writes stderr in the console code page, so "you’re" can arrive as one
    # undecodable byte; the runner decodes it as U+FFFD
    garbled = _warned(BOT_CHECK.replace("’", "�"))
    assert check_playability(CallResult(0, _page(), garbled)).code() == "bot-check"
