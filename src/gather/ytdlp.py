"""The yt-dlp edge: argv building, stderr triage, and one runner.

Pure helpers (``resolve_js_runtime``, ``base_argv``, ``failure_reason``, ``classify``,
``check_playability``) carry the decisions and are tested without the tool or network.
``subprocess_runner`` is the one impure call: it starts yt-dlp through ``gather.spawn``, like
every other child Gather starts, and callers take a ``Runner`` so tests can hand in a fake.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gather.spawn import ToolRefused, ToolUnavailable, find_tool, run_tool

DEFAULT_TIMEOUT = 120.0

# yt-dlp reads yt-dlp.conf from its working folder, the user's config and a file beside its
# executable, and a config can carry --exec. Gather passes its own flags only.
NO_CONFIG = ("--ignore-config",)

# Signals that the far side is throttling this client: HTTP 429 and YouTube's session rate limit.
# Backoff retries them under the same identity, within a bounded budget.
THROTTLE_CODES = frozenset({"rate-limited"})

# YouTube's "confirm you're not a bot" check. Gather detects it, stops, and leaves it to the person
# running it: the call is not retried, the record says so in plain words, and a channel pass stops.
# Gather never tries to answer or get around the check.
BOT_CHECK = "bot-check"
BOT_CHECK_STOPPED = "YouTube asked for a bot check, and gather stopped. It does not retry or answer a bot check."

# Failure codes that will not change on a retry without credentials or a change on the far side.
# A channel pass settles an entry that failed with one and does not ask for it again.
TERMINAL_CODES = frozenset({BOT_CHECK, "unavailable", "private", "members-only", "age-restricted"})

# Why YouTube served a video no formats. With --ignore-no-formats-error, yt-dlp prints the reason
# as an extractor warning and exits 0, so these codes are also read from warnings.
PLAYABILITY_CODES = THROTTLE_CODES | TERMINAL_CODES | frozenset({"geo-blocked", "upcoming"})

# An extractor's own warning, "WARNING: [youtube] ..."; yt-dlp's no-formats lines carry no "[...]".
_EXTRACTOR_WARNING = re.compile(r"WARNING: \[[^\]\s]+\] ")

_CLASSIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # a bot check is matched first, so a line that also names a rate limit still stops
    (BOT_CHECK, re.compile(r"confirm you.?re not a bot", re.I)),
    # YouTube's session limit reads "Video unavailable. This content isn't available, try again
    # later. The current session has been rate-limited by YouTube ...", so it is matched before
    # "unavailable"
    ("rate-limited", re.compile(r"HTTP Error 429|Too Many Requests|rate-limited by YouTube|try again later",
                                re.I)),
    ("age-restricted", re.compile(r"confirm your age|age.restricted|inappropriate for some users", re.I)),
    ("members-only", re.compile(r"members.only|join this channel", re.I)),
    ("private", re.compile(r"private video", re.I)),
    ("upcoming", re.compile(r"premieres in|live event will begin|is upcoming", re.I)),
    ("geo-blocked", re.compile(r"not (?:made this video )?available in your country", re.I)),
    ("no-formats", re.compile(r"requested format is not available|no video formats found", re.I)),
    ("unavailable", re.compile(r"video unavailable|video is unavailable|has been removed|"
                               r"no longer available|account associated with this video has been terminated",
                               re.I)),
    ("no-such-tab", re.compile(r"does not have an? \w+ tab", re.I)),
    ("forbidden", re.compile(r"HTTP Error 403", re.I)),
    ("tool-refused", re.compile(r"refused to run", re.I)),
    ("tool-missing", re.compile(r"could not run|No such file or directory|cannot find the file|"
                                r"not recognized", re.I)),
)


def resolve_js_runtime(setting: str | None, which: Callable[[str], str | None] = find_tool) -> str | None:
    """The ``--js-runtimes`` value to pass, or None to pass nothing.

    ``auto`` uses ``node`` when yt-dlp could start it: ``which`` defaults to the guarded
    lookup that also builds the child's PATH, so a ``node`` found only in the working folder
    does not count. ``none`` (or empty) disables the flag; any other value (``deno``,
    ``node:/opt/node/bin``) is passed through as given."""
    if setting is None:
        return None
    value = setting.strip()
    if not value or value.lower() == "none":
        return None
    if value.lower() == "auto":
        return "node" if which("node") else None
    return value


@dataclass(frozen=True, slots=True)
class YtDlpConfig:
    """How to invoke yt-dlp: the binary, a JS runtime setting, and yt-dlp's own pacing flags.

    ``timeout`` must be a finite number above 0: at 0 or below, every call would start yt-dlp
    and stop it at once. A sleep must be finite and not negative; 0 or None passes no flag."""

    binary: str = "yt-dlp"
    js_runtime: str | None = "auto"
    sleep_requests: float | None = None
    sleep_subtitles: float | None = None
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not (math.isfinite(self.timeout) and self.timeout > 0):
            raise ValueError(f"timeout must be a number of seconds above 0, got {self.timeout!r}")
        for name in ("sleep_requests", "sleep_subtitles"):
            value = getattr(self, name)
            if value is not None and not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{name} must be a number of seconds, 0 or more, got {value!r}")


def _num(value: float) -> str:
    return f"{value:g}"


def base_argv(cfg: YtDlpConfig, which: Callable[[str], str | None] = find_tool) -> list[str]:
    """The argv prefix every yt-dlp call shares: binary, ``--ignore-config``, JS runtime, and
    pacing flags."""
    argv = [cfg.binary, *NO_CONFIG]
    runtime = resolve_js_runtime(cfg.js_runtime, which)
    if runtime:
        argv += ["--js-runtimes", runtime]
    if cfg.sleep_requests:
        argv += ["--sleep-requests", _num(cfg.sleep_requests)]
    if cfg.sleep_subtitles:
        argv += ["--sleep-subtitles", _num(cfg.sleep_subtitles)]
    return argv


def without_impersonation(value: Any) -> Any:
    """A copy of an info JSON value with every ``impersonate`` key removed, at any depth.

    yt-dlp's YouTube extractor marks each caption track ``"impersonate": true``, and ``-J`` keeps
    the mark. Loaded back with ``--load-info-json``, it makes yt-dlp fetch the track with a
    browser's TLS fingerprint and headers whenever curl_cffi is importable where yt-dlp runs.
    Gather hands yt-dlp the info without it. Pure; the input is left as it is."""
    if isinstance(value, dict):
        return {k: without_impersonation(v) for k, v in value.items() if k != "impersonate"}
    if isinstance(value, list):
        return [without_impersonation(v) for v in value]
    return value


def failure_reason(stderr: str, *, limit: int = 400) -> str:
    """The line that explains a yt-dlp failure. Every ``ERROR`` line, joined; failing that, the
    last line that is not a ``WARNING``; failing that, the last line. A leading version or
    runtime warning never hides the real error."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR")]
    if errors:
        text = " | ".join(errors)
    else:
        plain = [ln for ln in lines if not ln.startswith("WARNING")]
        text = plain[-1] if plain else (lines[-1] if lines else "no error output")
    return text[:limit]


def classify(text: str) -> str:
    """A stable reason code for a failure message, for summaries and retry decisions."""
    for code, pattern in _CLASSIFIERS:
        if pattern.search(text or ""):
            return code
    return "error"


@dataclass(frozen=True, slots=True)
class CallResult:
    """One yt-dlp invocation's outcome. ``unplayable`` holds the extractor warning of a call
    that exited 0 but served no formats (see ``check_playability``); such a call is not ok."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    timeout: float | None = None
    unplayable: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.unplayable is None

    def reason(self) -> str:
        if self.timed_out:
            return f"timed out after {_num(self.timeout or 0)}s"
        if self.unplayable is not None:
            return f"served no formats: {self.unplayable}"[:400]
        return failure_reason(self.stderr)

    def code(self) -> str:
        # classify the explaining line, not all of stderr: a warning that mentions "not
        # available" must not turn a transient failure into a terminal one
        return "timeout" if self.timed_out else classify(self.reason())


Runner = Callable[[list[str], float], CallResult]


def _text(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


def subprocess_runner(argv: list[str], timeout: float) -> CallResult:
    """Run yt-dlp through ``gather.spawn``: an absolute executable (``GATHER_YT_DLP``, or the
    guarded PATH lookup), a new private empty working folder, and an environment allowlist
    that keeps the proxy and CA settings a network tool needs. ``argv[0]`` is a bare name or an
    absolute path; a relative path is refused.

    A timeout (after the whole process tree is stopped), a missing binary, or a refused start
    becomes a failed CallResult, not an exception, so a long channel run records it and moves
    on. Messages name the program as given, never a resolved path."""
    label = os.path.basename(argv[0])
    try:
        proc = run_tool(argv[0], argv[1:], timeout=timeout, network=True)
    except subprocess.TimeoutExpired:
        return CallResult(-1, "", "", timed_out=True, timeout=timeout)
    except ToolUnavailable as exc:
        return CallResult(127, "", f"ERROR: could not run {label}: {exc.strerror or exc}")
    except ToolRefused as exc:
        return CallResult(126, "", f"ERROR: refused to run {label} ({exc.code}): {exc}")
    return CallResult(proc.returncode, _text(proc.stdout), _text(proc.stderr))


def throttle_reason(result: CallResult) -> str | None:
    """The retry reason when a failed call is a throttle signal, else None. A bot check is not
    a throttle: it gets None, so it is never retried."""
    if result.ok:
        return None
    code = result.code()
    return f"{code}: {result.reason()}" if code in THROTTLE_CODES else None


def failure_text(result: CallResult, prefix: str = "yt-dlp failed: ") -> str:
    """What a failed call's record says. A bot check leads with a plain sentence that YouTube
    asked for one and Gather stopped, then yt-dlp's own line; any other failure is ``prefix``
    and that line."""
    if result.code() == BOT_CHECK:
        return f"{BOT_CHECK_STOPPED} yt-dlp said: {result.reason()}"
    return prefix + result.reason()


def playability_warning(stderr: str) -> str | None:
    """The extractor warning that says why a video was not served, or None.

    Only ``WARNING: [<extractor>] ...`` lines whose code is in ``PLAYABILITY_CODES`` count. A bot
    check line wins over any other, so a bot check always stops; then a throttle line, so a
    throttled session is retried, never settled; then the first line."""
    found = []
    for raw in (stderr or "").splitlines():
        line = raw.strip()
        if _EXTRACTOR_WARNING.match(line) and classify(line) in PLAYABILITY_CODES:
            found.append(line)

    def rank(line: str) -> int:
        code = classify(line)
        return 0 if code == BOT_CHECK else 1 if code in THROTTLE_CODES else 2

    return min(found, key=rank) if found else None


def _lists_formats(stdout: str) -> bool:
    """True unless ``stdout`` is an info document whose formats list is empty or missing.
    Output that is not an info document counts as True, so the caller's JSON check reports it."""
    try:
        info = json.loads(stdout)
    except ValueError:
        return True
    return not isinstance(info, dict) or bool(info.get("formats"))


def check_playability(result: CallResult) -> CallResult:
    """``result``, marked failed when a zero exit served no formats and said why.

    Gather extracts with ``--ignore-no-formats-error`` so a video whose formats are missing
    still yields its metadata and caption tracks. The same flag makes yt-dlp report YouTube's
    playability reason (a bot check, a session rate limit, a private or removed video) as a
    ``WARNING`` and exit 0. A call that listed no formats and carries such a warning is failed
    here with that line, so a throttle is retried and a terminal reason, a bot check among
    them, is recorded as one. A call that listed formats stays a success whatever its warnings
    say, and so does one that listed none and gave no reason."""
    if not result.ok:
        return result
    line = playability_warning(result.stderr)
    if line is None or _lists_formats(result.stdout):
        return result
    return dataclasses.replace(result, unplayable=line)
