"""A scripted stand-in for the yt-dlp CLI, for tests that exercise the live edge offline.

It answers the three call shapes Gather makes (flat listing, ``-J`` extraction, caption download
from ``--load-info-json``), records every argv it saw, and can be told to answer a step with
HTTP 429 a set number of times, or always.

A playability reason (a bot check, a session rate limit, a private video) gets the answer
yt-dlp 2026.08.19 gives. With ``--ignore-no-formats-error`` it prints the reason as an extractor
``WARNING``, then its two no-formats warnings, dumps the page's metadata with no formats and no
caption tracks, and exits 0. Without the flag it prints an ``ERROR`` and exits 1. A video that
lists no formats and gives no reason gets only the two no-formats warnings. ``fail`` answers
with a non-zero exit whatever the argv holds, for an error yt-dlp raises outright.
``caption_fail`` does the same for every caption download, and ``listing_fail`` for the listing
of a named tab.

Every caption track carries ``"impersonate": true``, as the YouTube extractor in yt-dlp 2026.08.19
marks each one, and ``caption_infos`` keeps the info JSON each caption download was handed.
"""

from __future__ import annotations

import json
import os
import re

from gather.ytdlp import CallResult

WARN = "WARNING: [youtube] yt-dlp 2026.08.19 is older than 90 days; update to get fixes\n"
ERR_429 = WARN + "ERROR: Unable to download video subtitles for 'en-orig': HTTP Error 429: Too Many Requests\n"
ERR_429_META = WARN + "ERROR: [youtube] abc: Unable to download API page: HTTP Error 429: Too Many Requests\n"

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello from {vid}\n"

# yt-dlp's own lines after an extraction that listed no formats, under --ignore-no-formats-error
NO_FORMATS = "WARNING: No video formats found!\nWARNING: Requested format is not available\n"

# Playability reasons, worded the way the YouTube extractor in yt-dlp 2026.08.19 words them
COOKIES_HINT = ("Use --cookies-from-browser or --cookies for the authentication. See  "
                "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to "
                "manually pass cookies. Also see  "
                "https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on "
                "effectively exporting YouTube cookies")
BOT_CHECK = f"Sign in to confirm you’re not a bot. {COOKIES_HINT}"
SESSION_LIMIT = ("Video unavailable. This content isn't available, try again later. The current session has "
                 "been rate-limited by YouTube for up to an hour. It is recommended to use `-t sleep` to add "
                 "a delay between video requests to avoid exceeding the rate limit. For more information, "
                 "refer to  https://github.com/yt-dlp/yt-dlp/wiki/Extractors"
                 "#this-content-isnt-available-try-again-later")
PRIVATE = f"Private video. Sign in if you've been granted access to this video. {COOKIES_HINT}"
REMOVED = "Video unavailable. This video has been removed by the uploader"
GEO = "Video unavailable. The uploader has not made this video available in your country"
UPCOMING = "Premieres in 3 hours"


def asr(lang: str, tlang: str | None = None) -> list[dict]:
    url = f"https://www.youtube.com/api/timedtext?v=x&kind=asr&lang={lang}&fmt=vtt"
    if tlang:
        url += f"&tlang={tlang}"
    return [{"ext": "vtt", "url": url, "impersonate": True}]


def video_info(vid: str, *, manual: tuple[str, ...] = (), auto: tuple[str, ...] = ("en-orig",),
               comments: int = 2, formats: bool = True) -> dict:
    return {
        "id": vid, "title": f"Title {vid}", "uploader": "Chan", "duration": 60,
        "upload_date": "20260101", "view_count": 5, "webpage_url": f"https://www.youtube.com/watch?v={vid}",
        "comment_count": comments,
        "formats": [{"format_id": "18", "ext": "mp4", "url": f"https://x/{vid}.mp4"}] if formats else [],
        "subtitles": {lang: [{"ext": "vtt", "url": f"https://x/{lang}", "impersonate": True}] for lang in manual},
        "automatic_captions": {lang: asr(lang.removesuffix("-orig")) for lang in auto},
        "_comments": [{"id": f"{vid}-c{i}", "text": f"comment {i} on {vid}", "author": f"user{i}"}
                      for i in range(comments)],
    }


class FakeYtDlp:
    def __init__(self, videos: dict[str, dict] | None = None, tabs: dict[str, list[str]] | None = None) -> None:
        self.videos = videos or {}
        self.tabs = tabs or {}
        self.calls: list[list[str]] = []
        self.throttle: dict[str, int] = {}  # step -> remaining 429 answers (-1 means always)
        self.fail: dict[str, str] = {}      # video id -> stderr to fail its extraction with
        # video id -> (playability reason, answers left; -1 means always)
        self.unplayable: dict[str, tuple[str, int]] = {}
        self.caption_infos: list[dict] = []  # the info JSON each caption download was handed
        self.caption_fail: str | None = None  # stderr to fail every caption download with
        self.listing_fail: dict[str, str] = {}  # tab -> stderr to fail its listing with

    def _throttled(self, step: str) -> bool:
        left = self.throttle.get(step, 0)
        if left == 0:
            return False
        if left > 0:
            self.throttle[step] = left - 1
        return True

    def _unplayable(self, vid: str) -> str | None:
        reason, left = self.unplayable.get(vid, ("", 0))
        if left == 0:
            return None
        if left > 0:
            self.unplayable[vid] = (reason, left - 1)
        return reason

    def __call__(self, argv: list[str], timeout: float) -> CallResult:
        self.calls.append(list(argv))
        if "--flat-playlist" in argv:
            return self._listing(argv[-1])
        if "--load-info-json" in argv:
            return self._captions(argv)
        return self._extract(argv)

    def _listing(self, url: str) -> CallResult:
        tab = url.rstrip("/").rsplit("/", 1)[-1]
        if tab in self.listing_fail:
            return CallResult(1, "", self.listing_fail[tab])
        if tab not in self.tabs:
            return CallResult(1, "", WARN + f"ERROR: [youtube:tab] chan: This channel does not have a {tab} tab\n")
        entries = [{"_type": "url", "ie_key": "Youtube", "id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}", "title": f"Title {vid}"}
                   for vid in self.tabs[tab]]
        return CallResult(0, json.dumps({"_type": "playlist", "id": "chan", "entries": entries}), "")

    def _extract(self, argv: list[str]) -> CallResult:
        vid = argv[-1].rsplit("=", 1)[-1]
        if vid in self.fail:
            return CallResult(1, "", self.fail[vid])
        if self._throttled("metadata"):
            return CallResult(1, "", ERR_429_META)
        lenient = "--ignore-no-formats-error" in argv
        reason = self._unplayable(vid)
        if reason is not None:
            if not lenient:
                return CallResult(1, "", WARN + f"ERROR: [youtube] {vid}: {reason}\n")
            page = {"id": vid, "title": f"Title {vid}", "formats": [], "subtitles": {}, "automatic_captions": {}}
            return CallResult(0, json.dumps(page), WARN + f"WARNING: [youtube] {reason}\n" + NO_FORMATS)
        info = dict(self.videos[vid])
        comments = info.pop("_comments", [])
        if "--write-comments" in argv:
            info["comments"] = comments
        if not info.get("formats"):
            if not lenient:
                return CallResult(1, "", WARN + f"ERROR: [youtube] {vid}: No video formats found!\n")
            return CallResult(0, json.dumps(info), WARN + NO_FORMATS)
        return CallResult(0, json.dumps(info), WARN)

    def _captions(self, argv: list[str]) -> CallResult:
        if self._throttled("captions"):
            return CallResult(1, "", ERR_429)
        if self.caption_fail is not None:
            return CallResult(1, "", self.caption_fail)
        with open(argv[argv.index("--load-info-json") + 1], encoding="utf-8") as f:
            info = json.load(f)
        self.caption_infos.append(info)
        assert "comments" not in info, "the caption call must not carry comments"
        lang = re.sub(r"\\(.)", r"\1", argv[argv.index("--sub-langs") + 1])
        out_dir = os.path.dirname(argv[argv.index("-o") + 1])
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"{info['id']}.{lang}.vtt"), "w", encoding="utf-8") as f:
            f.write(VTT.format(vid=info["id"]))
        return CallResult(0, "", WARN)
