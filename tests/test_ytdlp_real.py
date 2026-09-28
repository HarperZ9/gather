"""Playability handling against real yt-dlp code, not the scripted fake.

Each call runs yt-dlp's own command line (``yt_dlp.main``) in a child started through Gather's
real runner, with the argv Gather builds. A stand-in extractor, named ``youtube``, reports each
playability reason the way the YouTube extractor in yt-dlp 2026.08.19 does
(``extractor/youtube/_video.py``: ``raise_geo_restricted`` for a country block, then
``raise_no_formats(reason, expected=True)``), so the exit code, the warning lines and the info
JSON are yt-dlp's own. No network: the stand-in answers from memory, and the one caption track
it offers, marked for impersonation the way the YouTube extractor marks each track, is served
from 127.0.0.1. Skipped when yt-dlp is not importable.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fake_ytdlp import BOT_CHECK, NO_FORMATS, PRIVATE, FakeYtDlp

from gather.channel import outcome_row
from gather.channel_ledger import is_settled
from gather.pacing import BackoffPolicy
from gather.video_source import VideoSource
from gather.ytdlp import subprocess_runner

yt_dlp = pytest.importorskip("yt_dlp")

CHILD = r'''
import sys
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import remove_end

HINT = "Use --cookies-from-browser or --cookies for the authentication"
REASONS = {
    "botcheck": ("Sign in to confirm you’re not a bot. This helps protect our community. Learn more", ""),
    "ratelimit": ("Video unavailable", "This content isn't available, try again later."),
    "private": ("Private video", "Sign in if you've been granted access to this video"),
    "removed": ("Video unavailable", "This video has been removed by the uploader"),
    "geo": ("Video unavailable", "The uploader has not made this video available in your country"),
    "noformats": ("", ""),
    "partial429": ("", ""),
    "captioned": ("", ""),
}


class YoutubeStandInIE(InfoExtractor):
    IE_NAME = "youtube"
    _VALID_URL = r"standin:(?P<id>\w+)(?::(?P<port>\d+))?"

    def _real_extract(self, url):
        vid = self._match_id(url)
        reason, subreason = REASONS[vid]
        formats = []
        if vid == "captioned":  # one manual track on a local server, marked as yt-dlp marks YouTube's
            track = f"http://127.0.0.1:{self._match_valid_url(url).group('port')}/en.vtt"
            return {"id": vid, "title": "Title " + vid, "webpage_url": url, "automatic_captions": {},
                    "formats": [{"url": "https://example.invalid/v.mp4", "ext": "mp4", "format_id": "18"}],
                    "subtitles": {"en": [{"ext": "vtt", "url": track, "impersonate": True}]}}
        if vid == "partial429":  # one page failed, the rest of the extraction served formats
            self.report_warning("Unable to download webpage: HTTP Error 429: Too Many Requests", vid)
            formats = [{"url": "https://example.invalid/v.mp4", "ext": "mp4", "format_id": "18"}]
        if not formats:
            if subreason:
                if subreason.startswith("The uploader has not made this video available in your country"):
                    self.raise_geo_restricted(subreason, None, metadata_available=True)
                reason += f". {subreason}"
            if reason:
                if "sign in" in reason.lower():
                    reason = remove_end(reason, "This helps protect our community. Learn more")
                    reason = f'{remove_end(reason.strip(), ".")}. {HINT}'
                elif "This content isn't available, try again later" in reason:
                    reason = (f'{remove_end(reason.strip(), ".")}. The current session has been '
                              "rate-limited by YouTube for up to an hour.")
                self.raise_no_formats(reason, expected=True)
        return {"id": vid, "title": "Title " + vid, "formats": formats, "subtitles": {},
                "automatic_captions": {}, "webpage_url": url}


default = yt_dlp.YoutubeDL.add_default_info_extractors


def with_stand_in(self):
    self.add_info_extractor(YoutubeStandInIE())
    default(self)


yt_dlp.YoutubeDL.add_default_info_extractors = with_stand_in
sys.exit(yt_dlp.main(sys.argv[1:]))
'''

FAST = BackoffPolicy(base=0, cap=0, max_attempts=2, max_total_wait=0, jitter=0)


@pytest.fixture
def gather_standin(tmp_path):
    """Gather one stand-in video; returns its outcome and every (argv, raw result) of the calls."""
    script = tmp_path / "yt_dlp_stand_in.py"
    script.write_text(CHILD, encoding="utf-8")

    def run(vid):
        calls = []

        def runner(argv, timeout):
            res = subprocess_runner([sys.executable, str(script), *argv[1:]], timeout)
            calls.append((argv, res))
            return res

        src = VideoSource(runner=runner, captions="only", js_runtime="none", backoff=FAST,
                          sleep=lambda s: None, log=lambda m: None)
        return src.gather(f"standin:{vid}"), calls
    return run


@pytest.fixture
def caption_server():
    """A 127.0.0.1 server that answers every GET with one VTT and keeps each request's headers."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({k.lower(): v for k, v in self.headers.items()})
            body = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello from a local track\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port, seen
    server.shutdown()
    server.server_close()


def _row(out):
    return outcome_row(out, {"id": "x", "tab": "videos"}, "captions", {"added": 0, "deduped": 0}, 0.0)


@pytest.mark.parametrize("vid,code", [("botcheck", "bot-check"), ("ratelimit", "rate-limited")])
def test_a_real_throttle_warning_is_retried_and_left_pending(gather_standin, vid, code):
    out, calls = gather_standin(vid)
    assert "--ignore-no-formats-error" in calls[0][0] and calls[0][1].returncode == 0
    assert out.error_code == code and out.throttled and len(calls) == 2
    assert not is_settled(_row(out), "captions")


@pytest.mark.parametrize("vid,code,settled", [("private", "private", True), ("removed", "unavailable", True),
                                              ("geo", "geo-blocked", False)])
def test_a_real_playability_warning_fails_the_entry_without_a_retry(gather_standin, vid, code, settled):
    out, calls = gather_standin(vid)
    assert calls[0][1].returncode == 0
    assert out.error_code == code and not out.throttled and len(calls) == 1
    assert is_settled(_row(out), "captions") is settled


def test_real_no_formats_without_a_reason_is_still_a_success(gather_standin):
    out, calls = gather_standin("noformats")
    assert out.ok and out.caption == "missing" and out.caption_reason == "none-offered" and len(calls) == 1


def test_a_real_429_warning_on_a_call_that_served_formats_is_not_retried(gather_standin):
    out, calls = gather_standin("partial429")
    assert "HTTP Error 429" in calls[0][1].stderr
    assert out.ok and not out.attempts and len(calls) == 1


def _shape(res):
    """Exit code, each stderr line with an extractor warning cut to its prefix, and the formats."""
    lines = [ln for ln in res.stderr.splitlines() if "older than 90 days" not in ln]
    cut = [ln.split("]", 1)[0] + "]" if ln.startswith("WARNING: [") else ln for ln in lines]
    return res.returncode, cut, json.loads(res.stdout)["formats"]


@pytest.mark.parametrize("vid,reason", [("private", PRIVATE), ("botcheck", BOT_CHECK)], ids=["private", "bot-check"])
def test_the_fake_answers_in_the_shape_real_yt_dlp_prints(gather_standin, vid, reason):
    # the scripted fake the other suites use must answer the way real yt-dlp does
    _, calls = gather_standin(vid)
    argv, real = calls[0]
    fake = FakeYtDlp({})
    fake.unplayable["abc"] = (reason, -1)
    scripted = fake([*argv[:-1], "https://www.youtube.com/watch?v=abc"], 60)
    assert _shape(real) == _shape(scripted) == (0, ["WARNING: [youtube]", *NO_FORMATS.splitlines()], [])


def test_a_real_caption_download_goes_out_as_yt_dlp_not_as_a_browser(gather_standin, caption_server):
    # yt-dlp marks every YouTube caption track "impersonate": true. With curl_cffi importable it
    # would fetch the track with a browser's TLS fingerprint and headers (sec-ch-ua, a browser's
    # Accept-Language in place of yt-dlp's own); without it, yt-dlp warns that it cannot.
    port, seen = caption_server
    out, calls = gather_standin(f"captioned:{port}")
    assert out.ok and out.caption == "manual" and len(calls) == 2 and len(seen) == 1
    assert json.loads(calls[0][1].stdout)["subtitles"]["en"][0]["impersonate"] is True   # -J keeps the mark
    assert "hello from a local track" in next(i for i in out.items if i.kind == "transcript").text
    headers = seen[0]
    assert not any(name.startswith("sec-ch-ua") for name in headers)
    assert headers.get("accept-language") == yt_dlp.utils.networking.std_headers["Accept-Language"]
    assert "impersonat" not in calls[1][1].stderr.lower()
