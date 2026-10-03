"""On MCP, a video job's Data API fallback needs a credential grant bound to the API host."""
from test_grants import _call, _refusal, sealed  # noqa: F401  (fixture re-export)

from gather.grants import Grants
from gather.run_config import build_source
from gather.youtube_route import YouTubeRoute

JOB = {"source": "video", "target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
       "api_key_env": "GATHER_YOUTUBE_API_KEY"}


def test_a_video_job_naming_a_key_needs_the_credential_grant(sealed):  # noqa: F811
    net_only = Grants(network_sources=frozenset({"video"}))
    body = _refusal(_call("gather.run", {"config": {"jobs": [JOB]}}, grants=net_only))
    assert body["code"] == "GRANT_REQUIRED" and body["setup"] == "GATHER_AUTH_ENV_ALLOW"
    assert sealed == []


def test_a_credential_grant_for_another_host_does_not_cover_the_api(sealed):  # noqa: F811
    grants = Grants(network_sources=frozenset({"video"}),
                    auth_env=frozenset({("GATHER_YOUTUBE_API_KEY", "api.example.org")}))
    assert _refusal(_call("gather.run", {"config": {"jobs": [JOB]}}, grants=grants))["code"] == "GRANT_REQUIRED"


def test_build_source_turns_the_fallback_on_only_when_the_job_names_a_key():
    with_key = build_source("video", JOB)
    without = build_source("video", {"source": "video", "target": JOB["target"]})
    assert isinstance(with_key, YouTubeRoute) and isinstance(without, YouTubeRoute)
    assert with_key._api is not None and with_key._api.key_env == "GATHER_YOUTUBE_API_KEY"
    assert without._api is None
