"""The Data API fallback's pure parts: video ids, durations and the yt-dlp-shaped info."""
import json

import pytest

from gather.credentials import MissingCredential
from gather.youtube_api import DataApiClient, info_from_api, iso_duration, video_id


@pytest.mark.parametrize("target", [
    "dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10",
    "https://youtu.be/dQw4w9WgXcQ?si=x",
    "https://m.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
])
def test_video_id_reads_single_video_forms(target):
    assert video_id(target) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("target", [
    "https://www.youtube.com/@chan", "https://www.youtube.com/playlist?list=PL1",
    "https://evil.example/watch?v=dQw4w9WgXcQ", "https://notyoutube.com/watch?v=dQw4w9WgXcQ", "short",
])
def test_video_id_refuses_everything_else(target):
    assert video_id(target) is None


@pytest.mark.parametrize("value,secs", [("PT1H2M3S", 3723), ("PT45S", 45), ("P1DT1S", 86401), ("PT0S", 0)])
def test_iso_duration(value, secs):
    assert iso_duration(value) == secs


@pytest.mark.parametrize("value", ["P", "1:00", None, 60])
def test_iso_duration_rejects_non_durations(value):
    assert iso_duration(value) is None


def test_info_from_api_maps_to_yt_dlp_field_names():
    body = json.dumps({"items": [{"id": "dQw4w9WgXcQ", "snippet": {"title": "T", "channelTitle": "C",
                                                                   "publishedAt": "2009-10-25T06:57:33Z"},
                                  "contentDetails": {"duration": "PT3M33S"},
                                  "statistics": {"viewCount": "100"}}]})
    info = info_from_api(body, "dQw4w9WgXcQ")
    assert info == {"id": "dQw4w9WgXcQ", "title": "T", "uploader": "C", "duration": 213,
                    "upload_date": "20091025", "view_count": 100, "comment_count": None,
                    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}


def test_info_from_api_raises_on_a_missing_video_and_on_bad_json():
    with pytest.raises(LookupError):
        info_from_api('{"items": [{"id": "other"}]}', "dQw4w9WgXcQ")
    with pytest.raises(ValueError):
        info_from_api("<html>", "dQw4w9WgXcQ")
    with pytest.raises(ValueError):
        info_from_api('{"error": {}}', "dQw4w9WgXcQ")


def test_client_needs_the_key_and_names_only_the_variable(monkeypatch):
    monkeypatch.delenv("MY_YT_KEY", raising=False)
    client = DataApiClient(key_env="MY_YT_KEY", http=lambda *a, **k: pytest.fail("no request without a key"))
    with pytest.raises(MissingCredential, match="MY_YT_KEY"):
        client.fetch_info("dQw4w9WgXcQ")
