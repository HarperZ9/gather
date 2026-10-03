"""On MCP a reddit job needs the network grant and credential grants bound to the token host."""
from test_grants import _call, _refusal, sealed  # noqa: F401

from gather.grants import NETWORK_SOURCES, Grants

JOB = {"source": "reddit", "target": "r/python"}
BOTH = frozenset({("REDDIT_CLIENT_ID", "www.reddit.com"), ("REDDIT_CLIENT_SECRET", "www.reddit.com")})


def test_reddit_is_a_network_source():
    assert "reddit" in NETWORK_SOURCES


def test_no_network_grant_is_refused(sealed):  # noqa: F811
    body = _refusal(_call("gather.run", {"config": {"jobs": [JOB]}}))
    assert body["setup"] == "GATHER_ALLOW_NETWORK" and sealed == []


def test_network_without_credential_grants_is_refused(sealed):  # noqa: F811
    grants = Grants(network_sources=frozenset({"reddit"}),
                    auth_env=frozenset({("REDDIT_CLIENT_ID", "www.reddit.com")}))
    body = _refusal(_call("gather.run", {"config": {"jobs": [JOB]}}, grants=grants))
    assert body["setup"] == "GATHER_AUTH_ENV_ALLOW" and sealed == []


def test_grants_bound_to_another_host_do_not_cover_reddit(sealed):  # noqa: F811
    grants = Grants(network_sources=frozenset({"reddit"}),
                    auth_env=frozenset({(n, "oauth.reddit.com") for n, _ in BOTH}))
    assert _refusal(_call("gather.run", {"config": {"jobs": [JOB]}}, grants=grants))["code"] == "GRANT_REQUIRED"
