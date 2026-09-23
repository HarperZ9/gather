"""The yt-dlp edge: argv building, stderr triage, and one subprocess runner.

Pure helpers (``resolve_js_runtime``, ``base_argv``, ``failure_reason``, ``classify``) carry
the decisions and are tested without the tool or network. ``subprocess_runner`` is the one
impure call, and callers take a ``Runner`` so tests can hand in a fake.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_TIMEOUT = 120.0

# Signals that the far side is throttling this client. Backoff treats both as retryable; the
# bot check is YouTube asking the client to slow down, and waiting is the only answer Gather gives.
THROTTLE_CODES = frozenset({"rate-limited", "bot-check"})

# Failure codes that will not change on a retry without credentials or a change on the far side.
TERMINAL_CODES = frozenset({"unavailable", "private", "members-only", "age-restricted"})

_CLASSIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rate-limited", re.compile(r"HTTP Error 429|Too Many Requests", re.I)),
    ("bot-check", re.compile(r"confirm you.?re not a bot", re.I)),
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
    ("tool-missing", re.compile(r"No such file or directory|cannot find the file|not recognized", re.I)),
)


def resolve_js_runtime(setting: str | None, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The ``--js-runtimes`` value to pass, or None to pass nothing.

    ``auto`` uses ``node`` when it is on PATH; ``none`` (or empty) disables the flag; any other
    value (``deno``, ``node:/opt/node/bin``) is passed through as given."""
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
    """How to invoke yt-dlp: the binary, a JS runtime setting, and yt-dlp's own pacing flags."""

    binary: str = "yt-dlp"
    js_runtime: str | None = "auto"
    sleep_requests: float | None = None
    sleep_subtitles: float | None = None
    timeout: float = DEFAULT_TIMEOUT


def _num(value: float) -> str:
    return f"{value:g}"


def base_argv(cfg: YtDlpConfig, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """The argv prefix every yt-dlp call shares: binary, JS runtime, and pacing flags."""
    argv = [cfg.binary]
    runtime = resolve_js_runtime(cfg.js_runtime, which)
    if runtime:
        argv += ["--js-runtimes", runtime]
    if cfg.sleep_requests:
        argv += ["--sleep-requests", _num(cfg.sleep_requests)]
    if cfg.sleep_subtitles:
        argv += ["--sleep-subtitles", _num(cfg.sleep_subtitles)]
    return argv


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
    """One yt-dlp invocation's outcome."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    timeout: float | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def reason(self) -> str:
        if self.timed_out:
            return f"timed out after {_num(self.timeout or 0)}s"
        return failure_reason(self.stderr)

    def code(self) -> str:
        # classify the explaining line, not all of stderr: a warning that mentions "not
        # available" must not turn a transient failure into a terminal one
        return "timeout" if self.timed_out else classify(self.reason())


Runner = Callable[[list[str], float], CallResult]


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def subprocess_runner(argv: list[str], timeout: float) -> CallResult:
    """Run yt-dlp. A timeout or a missing binary becomes a failed CallResult, not an exception,
    so a long channel run records it and moves on."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return CallResult(-1, _text(exc.stdout), _text(exc.stderr), timed_out=True, timeout=timeout)
    except OSError as exc:
        return CallResult(127, "", f"ERROR: could not run {argv[0]!r}: {exc}")
    return CallResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def throttle_reason(result: CallResult) -> str | None:
    """The retry reason when a failed call is a throttle signal, else None."""
    if result.ok:
        return None
    code = result.code()
    return f"{code}: {result.reason()}" if code in THROTTLE_CODES else None
