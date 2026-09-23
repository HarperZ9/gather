import sys

import pytest

from gather.ytdlp import (
    CallResult,
    YtDlpConfig,
    base_argv,
    classify,
    failure_reason,
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
    assert base_argv(cfg, on_path) == ["yt-dlp", "--js-runtimes", "node", "--sleep-requests", "1.5",
                                       "--sleep-subtitles", "20"]
    assert base_argv(YtDlpConfig(js_runtime="auto"), not_on_path) == ["yt-dlp"]


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
