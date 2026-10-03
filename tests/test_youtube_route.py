"""yt-dlp is the primary YouTube path; the Data API serves metadata only as a keyed fallback."""
import json

import pytest
from fake_ytdlp import BOT_CHECK, GEO, PRIVATE, REMOVED, UPCOMING, FakeYtDlp, video_info

from gather.pacing import BackoffPolicy
from gather.source import Catalog
from gather.video_source import VideoSource
from gather.youtube_api import DataApiClient
from gather.youtube_route import (
    API_CAPTION_REASON,
    FALLBACK_CODES,
    YouTubeRoute,
    fallback_wanted,
)

KEY = "AIzaTEST-not-a-real-key-123"
FAST = BackoffPolicy(base=1, factor=2, cap=10, max_attempts=2, max_total_wait=10, jitter=0)
URL = "https://www.youtube.com/watch?v=abcdefghijk"
VID = "abcdefghijk"


def api_payload(vid=VID):
    return json.dumps({"items": [{
        "id": vid,
        "snippet": {"title": f"API {vid}", "channelTitle": "Chan", "publishedAt": "2026-01-02T03:04:05Z"},
        "contentDetails": {"duration": "PT1M5S"},
        "statistics": {"viewCount": "42", "commentCount": "3"},
    }]}).encode()


class FakeHttp:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.calls = body if body is not None else api_payload(), error, []

    def __call__(self, url, *, timeout, headers):
        self.calls.append({"url": url, "headers": dict(headers)})
        if self.error:
            raise self.error
        return self.body, "application/json"


class Tick:
    def __init__(self, step=0.5):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def make(fake, *, http=None, key=True, monkeypatch=None, captions="with", api=True):
    if monkeypatch is not None:
        if key:
            monkeypatch.setenv("GATHER_YOUTUBE_API_KEY", KEY)
        else:
            monkeypatch.delenv("GATHER_YOUTUBE_API_KEY", raising=False)
    logs = []
    client = DataApiClient(http=http or FakeHttp(), clock=Tick(0.25)) if api else None
    route = YouTubeRoute(
        source_factory=lambda r: VideoSource(runner=r, backoff=FAST, sleep=lambda s: None,
                                             rand=lambda: 0.5, log=logs.append, captions=captions,
                                             which=lambda n: None, clock=lambda: 1.0),
        runner=fake, api=client, clock=Tick(1.0), wall=lambda: 7.0, log=logs.append)
    return route, logs


def test_healthy_yt_dlp_serves_every_item_and_makes_no_api_request(monkeypatch):
    fake, http = FakeYtDlp({VID: video_info(VID)}), FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch)
    routed = route.gather(URL)
    assert routed.outcome.ok and http.calls == []
    assert {i.meta["route"]["path"] for i in routed.outcome.items} == {"yt-dlp"}
    rec = routed.route.to_dict()
    assert rec["requests"] == 2 and rec["elapsed_s"] == 2.0  # one extraction, one caption track
    assert rec["bytes"] > 0 and rec["bytes_per_s"] == round(rec["bytes"] / 2.0, 1)
    assert rec["requests_per_min"] == 60.0 and rec["auth"] == "absent" and "fallback_reason" not in rec
    transcript = next(i for i in routed.outcome.items if i.kind == "transcript")
    call_bytes = sum(c["bytes"] for c in route._timed.calls)
    assert rec["bytes"] == call_bytes + len(transcript.text.encode("utf-8")), "caption file bytes count"


def test_throttled_yt_dlp_falls_back_to_the_data_api_when_a_key_is_set(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    http = FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch)
    routed = route.gather(URL)
    out = routed.outcome
    assert out.ok and len(http.calls) == 1
    assert [i.kind for i in out.items] == ["metadata"]
    item = out.items[0]
    assert item.provenance.method == "youtube-data-api" and item.title == f"API {VID}"
    meta = json.loads(item.text)
    assert meta["duration"] == 65 and meta["upload_date"] == "20260102" and meta["view_count"] == 42
    rec = item.meta["route"]
    assert rec["path"] == "youtube-data-api" and rec["auth"] == "present"
    assert rec["fallback_reason"].startswith("rate-limited") and rec["elapsed_s"] == 0.25
    assert rec["extra"] == {"quota_units": 1}
    assert out.caption == "missing" and out.caption_reason == API_CAPTION_REASON


def test_a_bot_check_ends_yt_dlp_and_the_official_api_reads_the_metadata(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.unplayable[VID] = (BOT_CHECK, -1)
    http = FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch)
    out = route.gather(URL).outcome
    assert len(fake.calls) == 1, "a bot check is never retried on yt-dlp"
    assert out.ok and out.items[0].meta["route"]["fallback_reason"].startswith("bot-check")


def test_without_a_key_the_failure_stands_and_no_request_is_made(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    http = FakeHttp()
    route, logs = make(fake, http=http, key=False, monkeypatch=monkeypatch)
    routed = route.gather(URL)
    assert not routed.outcome.ok and routed.route is None and http.calls == []
    assert any("GATHER_YOUTUBE_API_KEY" in line for line in logs)
    with pytest.raises(RuntimeError):
        route.fetch(URL)


def test_no_api_fallback_keeps_every_read_on_yt_dlp(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    route, _ = make(fake, monkeypatch=monkeypatch, api=False)
    assert not route.gather(URL).outcome.ok


@pytest.mark.parametrize("reason", [PRIVATE, REMOVED, GEO, UPCOMING])
def test_a_verdict_about_the_video_never_triggers_the_fallback(reason, monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.unplayable[VID] = (reason, -1)
    http = FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch)
    out = route.gather(URL).outcome
    assert not out.ok and http.calls == []
    assert out.error_code not in FALLBACK_CODES


def test_captions_only_pass_does_not_fall_back(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    http = FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch, captions="only")
    assert not route.gather(URL).outcome.ok and http.calls == []


def test_the_key_travels_in_a_header_and_appears_nowhere_else(monkeypatch, capsys):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    http = FakeHttp()
    route, logs = make(fake, http=http, monkeypatch=monkeypatch)
    items = route.fetch(URL)
    call = http.calls[0]
    assert call["headers"] == {"X-Goog-Api-Key": KEY} and KEY not in call["url"]
    witnessed = Catalog()
    witnessed.add(items)
    blob = witnessed.to_json() + json.dumps([i.meta for i in items]) + "\n".join(logs)
    blob += "".join(capsys.readouterr())
    assert KEY not in blob


def test_an_api_failure_keeps_the_yt_dlp_error_and_adds_the_api_reason(monkeypatch):
    fake = FakeYtDlp({VID: video_info(VID)})
    fake.throttle["metadata"] = -1
    route, _ = make(fake, http=FakeHttp(body=b'{"items": []}'), monkeypatch=monkeypatch)
    out = route.gather(URL).outcome
    assert not out.ok and "429" in out.error and "Data API fallback failed" in out.error


def test_a_channel_url_cannot_use_the_single_video_fallback(monkeypatch):
    fake = FakeYtDlp({})
    fake.fail["https://www.youtube.com/@chan"] = "ERROR: boom\n"
    http = FakeHttp()
    route, _ = make(fake, http=http, monkeypatch=monkeypatch)
    routed = route.gather("https://www.youtube.com/@chan")
    assert not routed.outcome.ok and http.calls == [] and routed.notes


def test_fallback_wanted_reads_the_path_codes_only():
    from gather.video_source import VideoOutcome
    assert fallback_wanted(VideoOutcome(target="x", error="e", error_code="timeout"))
    assert not fallback_wanted(VideoOutcome(target="x", error="e", error_code="private"))
    assert not fallback_wanted(VideoOutcome(target="x"))
