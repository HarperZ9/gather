"""The live video edge: yt-dlp for metadata, comments, and one chosen caption track.

``VideoSource.gather`` returns a ``VideoOutcome`` that says what happened at each step (the
caption kind or the reason it is missing, every throttle retry, the real failure line), so a
channel run can count outcomes instead of guessing. ``fetch`` keeps the adapter contract: a
list of Items, RuntimeError when the metadata call fails.

Caption intake runs as two yt-dlp calls: one extraction (``-J``) that lists the tracks, then one
download of exactly the chosen track from the saved info JSON (``--load-info-json``), so the
caption endpoint sees one request per video and a throttle retry never re-extracts the page.
``captions`` selects the pass: ``with`` (default), ``skip`` (metadata and comments only), or
``only`` (the transcript item only).
"""

from __future__ import annotations

import glob
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from gather.captions import CaptionChoice, select_caption_track
from gather.item import Item
from gather.pacing import BackoffPolicy, Pacer, run_with_backoff
from gather.ytdlp import (
    DEFAULT_TIMEOUT,
    CallResult,
    Runner,
    YtDlpConfig,
    base_argv,
    subprocess_runner,
    throttle_reason,
)

CAPTION_MODES = ("with", "skip", "only")

# A single interactive fetch should not sit in backoff for half an hour; channel runs pass their own.
DEFAULT_BACKOFF = BackoffPolicy(base=15.0, factor=2.0, cap=120.0, max_attempts=3, max_total_wait=180.0)


@dataclass(slots=True)
class VideoOutcome:
    """What one video's intake produced and why. ``error`` is set when the metadata call failed
    (the video yields no items). ``caption`` is ``manual``, ``auto``, ``missing`` (see
    ``caption_reason``), or ``skipped``. ``throttled`` is True when a step ran out of backoff
    budget while still throttled."""

    target: str
    items: list[Item] = field(default_factory=list)
    video_id: str = ""
    title: str = ""
    error: str | None = None
    error_code: str | None = None
    caption: str = "skipped"
    caption_lang: str | None = None
    caption_reason: str | None = None
    caption_detail: str = ""
    comments: int = 0
    comment_count_reported: int | None = None
    attempts: list[dict] = field(default_factory=list)
    throttled: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


class VideoSource:
    """Video intake (metadata, captions, comments) via the yt-dlp CLI.

    The isolated impure edge: it shells out to ``yt-dlp`` (an external tool, not a Python
    dependency) and parses the result with the pure ``items_from_info``. Every collaborator
    with a side effect (runner, sleep, random, clock, PATH lookup) is injectable, so the
    decisions are tested without the tool or network."""

    name = "video"

    def __init__(self, *, clock: Callable[[], float] = time.time, yt_dlp: str = "yt-dlp",
                 with_comments: bool = False, timeout: float = DEFAULT_TIMEOUT,
                 captions: str = "with", caption_langs: Sequence[str] = ("en",),
                 js_runtime: str | None = "auto", sleep_requests: float | None = None,
                 sleep_subtitles: float | None = None, backoff: BackoffPolicy | None = None,
                 runner: Runner | None = None, sleep: Callable[[float], None] = time.sleep,
                 rand: Callable[[], float] = random.random, pacer: Pacer | None = None,
                 log: Callable[[str], None] | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        if captions not in CAPTION_MODES:
            raise ValueError(f"captions must be one of {CAPTION_MODES}, got {captions!r}")
        self._clock = clock
        self._with_comments = with_comments
        self._captions = captions
        self._langs = tuple(caption_langs) or ("en",)
        self._cfg = YtDlpConfig(binary=yt_dlp, js_runtime=js_runtime, sleep_requests=sleep_requests,
                                sleep_subtitles=sleep_subtitles, timeout=timeout)
        self._base = base_argv(self._cfg, which)
        self._backoff = backoff or DEFAULT_BACKOFF
        self._runner = runner or subprocess_runner
        self._sleep = sleep
        self._rand = rand
        self._pacer = pacer
        self._log = log or (lambda msg: print(msg, file=sys.stderr))

    @property
    def base_argv(self) -> list[str]:
        return list(self._base)

    def fetch(self, target: str) -> list[Item]:
        """Fetch one video's items. Raises RuntimeError with the real yt-dlp ERROR line when the
        metadata call fails. Caption failures are logged to stderr, not treated as absent."""
        out = self.gather(target)
        if out.error is not None:
            raise RuntimeError(out.error)
        return list(out.items)

    def gather(self, target: str) -> VideoOutcome:
        """Run the configured pass for one video and report every step's outcome."""
        # imported here, not at module top: gather.video re-exports this module
        from gather.video import items_from_info

        out = VideoOutcome(target=target)
        info = self._extract(target, out)
        if info is None:
            if self._captions != "skip":  # the caption step never ran; say why
                out.caption, out.caption_reason = "missing", out.error_code
                out.caption_detail = f"not attempted: {out.error}"
            return out
        out.video_id = str(info.get("id", ""))
        out.title = str(info.get("title", ""))
        reported = info.get("comment_count")
        out.comment_count_reported = reported if isinstance(reported, int) else None
        vtt = self._captions_for(info, out) if self._captions != "skip" else None
        items = items_from_info(info, vtt, fetched_at=float(self._clock()), method="yt-dlp",
                                auto_captions=out.caption == "auto",
                                caption_lang=out.caption_lang if vtt else None)
        if self._captions == "only":
            items = [i for i in items if i.kind == "transcript"]
        out.items = items
        out.comments = sum(1 for i in items if i.kind == "comment")
        return out

    def list_entries(self, url: str, *, timeout: float = 300.0) -> tuple[CallResult, VideoOutcome]:
        """List a channel tab or playlist without resolving each entry (``--flat-playlist``).
        Returns the raw call result (its stdout is yt-dlp's JSON) and an outcome carrying the
        retry record; a long tab gets at least ``timeout`` seconds."""
        out = VideoOutcome(target=url)
        argv = self._base + ["--flat-playlist", "--dump-single-json", "--", url]
        res = self._call(argv, "listing", out, timeout=max(timeout, self._cfg.timeout))
        if not res.ok:
            out.error, out.error_code = f"yt-dlp failed: {res.reason()}", res.code()
        return res, out

    def _call(self, argv: list[str], step: str, out: VideoOutcome, *,
              timeout: float | None = None) -> CallResult:
        """Run yt-dlp with bounded backoff on throttle signals; record every retry and the
        final failure on ``out`` and in the log."""
        limit = self._cfg.timeout if timeout is None else timeout
        result = run_with_backoff(
            lambda: self._runner(argv, limit), retryable=throttle_reason,
            policy=self._backoff, step=step, sleep=self._sleep, rand=self._rand,
            on_retry=lambda r: self._log(
                f"gather: yt-dlp {step} throttled ({r['reason'][:160]}); "
                f"retry {r['attempt']}/{self._backoff.max_attempts} in {r['wait_s']:.1f}s"),
            pacer=self._pacer)
        out.attempts.extend(result.attempts)
        if result.exhausted:
            out.throttled = True
            out.attempts.append({"step": step, "attempt": len(result.attempts) + 1,
                                 "reason": result.retry_reason, "wait_s": 0.0, "final": True})
            self._log(f"gather: yt-dlp {step} still throttled after {len(result.attempts) + 1} "
                      f"attempt(s); backoff budget spent")
        return result.value

    def _extract(self, target: str, out: VideoOutcome) -> dict | None:
        argv = self._base + ["--dump-single-json", "--skip-download", "--ignore-no-formats-error"]
        if self._with_comments and self._captions != "only":
            argv.append("--write-comments")
        argv += ["--", target]  # end-of-options: a target starting with - cannot be read as a flag
        res = self._call(argv, "metadata", out)
        if not res.ok:
            out.error, out.error_code = f"yt-dlp failed: {res.reason()}", res.code()
            return None
        try:
            info = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            out.error, out.error_code = f"yt-dlp failed: not valid yt-dlp JSON: {exc}", "bad-json"
            return None
        if not isinstance(info, dict):
            out.error, out.error_code = "yt-dlp failed: the JSON top level is not an object", "bad-json"
            return None
        return info

    def _captions_for(self, info: dict, out: VideoOutcome) -> str | None:
        pick = select_caption_track(info, self._langs)
        if pick.choice is None:
            out.caption, out.caption_reason, out.caption_detail = "missing", pick.reason, pick.detail
            return None
        out.caption_lang = pick.choice.lang
        vtt, res = self._download_track(info, pick.choice, out)
        if vtt is None:
            out.caption = "missing"
            out.caption_reason = "no-vtt" if res.ok else res.code()
            out.caption_detail = "yt-dlp wrote no .vtt file" if res.ok else res.reason()
            kind = "auto" if pick.choice.auto else "manual"
            self._log(f"gather: yt-dlp {kind} captions ({pick.choice.lang}) failed: {out.caption_detail[:200]}")
            return None
        out.caption = "auto" if pick.choice.auto else "manual"
        return vtt

    def _download_track(self, info: dict, choice: CaptionChoice,
                        out: VideoOutcome) -> tuple[str | None, CallResult]:
        """Download exactly one track from the saved info JSON (no re-extraction)."""
        flag = "--write-auto-subs" if choice.auto else "--write-subs"
        slim = {k: v for k, v in info.items() if k != "comments"}
        with tempfile.TemporaryDirectory() as d:
            info_path = os.path.join(d, "info.json")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(slim, f)
            subs = os.path.join(d, "subs")
            argv = self._base + [
                "--load-info-json", info_path, "--skip-download", "--ignore-no-formats-error", flag,
                "--sub-langs", re.escape(choice.lang), "--sub-format", "vtt",
                "-o", os.path.join(subs, "%(id)s.%(ext)s"),
            ]
            res = self._call(argv, "captions", out)
            vtts = sorted(glob.glob(os.path.join(subs, "*.vtt")))
            if not vtts:
                return None, res
            with open(vtts[0], encoding="utf-8") as f:
                return f.read(), res
