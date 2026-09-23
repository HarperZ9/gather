"""A scripted stand-in for the yt-dlp CLI, for tests that exercise the live edge offline.

It answers the three call shapes Gather makes (flat listing, ``-J`` extraction, caption download
from ``--load-info-json``), records every argv it saw, and can be told to answer a step with
HTTP 429 a set number of times, or always.
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


def asr(lang: str, tlang: str | None = None) -> list[dict]:
    url = f"https://www.youtube.com/api/timedtext?v=x&kind=asr&lang={lang}&fmt=vtt"
    if tlang:
        url += f"&tlang={tlang}"
    return [{"ext": "vtt", "url": url}]


def video_info(vid: str, *, manual: tuple[str, ...] = (), auto: tuple[str, ...] = ("en-orig",),
               comments: int = 2) -> dict:
    return {
        "id": vid, "title": f"Title {vid}", "uploader": "Chan", "duration": 60,
        "upload_date": "20260101", "view_count": 5, "webpage_url": f"https://www.youtube.com/watch?v={vid}",
        "comment_count": comments,
        "subtitles": {lang: [{"ext": "vtt", "url": f"https://x/{lang}"}] for lang in manual},
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

    def _throttled(self, step: str) -> bool:
        left = self.throttle.get(step, 0)
        if left == 0:
            return False
        if left > 0:
            self.throttle[step] = left - 1
        return True

    def __call__(self, argv: list[str], timeout: float) -> CallResult:
        self.calls.append(list(argv))
        if "--flat-playlist" in argv:
            return self._listing(argv[-1])
        if "--load-info-json" in argv:
            return self._captions(argv)
        return self._extract(argv)

    def _listing(self, url: str) -> CallResult:
        tab = url.rstrip("/").rsplit("/", 1)[-1]
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
        info = dict(self.videos[vid])
        comments = info.pop("_comments", [])
        if "--write-comments" in argv:
            info["comments"] = comments
        return CallResult(0, json.dumps(info), WARN)

    def _captions(self, argv: list[str]) -> CallResult:
        if self._throttled("captions"):
            return CallResult(1, "", ERR_429)
        with open(argv[argv.index("--load-info-json") + 1], encoding="utf-8") as f:
            info = json.load(f)
        assert "comments" not in info, "the caption call must not carry comments"
        lang = re.sub(r"\\(.)", r"\1", argv[argv.index("--sub-langs") + 1])
        out_dir = os.path.dirname(argv[argv.index("-o") + 1])
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"{info['id']}.{lang}.vtt"), "w", encoding="utf-8") as f:
            f.write(VTT.format(vid=info["id"]))
        return CallResult(0, "", WARN)
