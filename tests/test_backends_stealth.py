"""Stealth transport: redirect handling, credential stripping, transient 5xx.

Offline via a fake curl_cffi-style client; the SSRF guard (net.validate_public_
http_url, tested in net's own suite) is patched to identity here to avoid DNS."""
from __future__ import annotations

from importlib.util import find_spec

import pytest

import gather.backends_stealth as bs
from gather.fetch import TransientFetchError


class FakeResp:
    def __init__(self, status, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, *, headers, timeout, impersonate, allow_redirects):
        self.calls.append({"url": url, "headers": dict(headers)})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr(bs, "validate_public_http_url", lambda u: u)


def test_available_matches_find_spec() -> None:
    assert bs.curl_cffi_available() == (find_spec("curl_cffi") is not None)


def test_returns_rawresponse_for_200() -> None:
    client = FakeClient(FakeResp(200, {"content-type": "text/html"}, b"<html>ok</html>"))
    raw = bs.stealth_transport("http://e.com/", headers={"User-Agent": "x"},
                               timeout=5, max_bytes=1000, client=client)
    assert raw.status == 200 and raw.body == b"<html>ok</html>"
    assert raw.final_url == "http://e.com/"


def test_follows_redirects_and_strips_cross_origin_credentials() -> None:
    client = FakeClient(
        FakeResp(302, {"location": "http://other.com/x"}, b""),
        FakeResp(200, {}, b"final"),
    )
    raw = bs.stealth_transport(
        "http://e.com/", headers={"Authorization": "Bearer t", "User-Agent": "x"},
        timeout=5, max_bytes=1000, client=client,
    )
    assert raw.status == 200 and raw.body == b"final"
    assert [r.status for r in raw.redirects] == [302]
    assert "Authorization" not in client.calls[1]["headers"]  # dropped across origin
    assert "User-Agent" in client.calls[1]["headers"]         # kept


def test_5xx_is_transient() -> None:
    client = FakeClient(FakeResp(503, {}, b""))
    with pytest.raises(TransientFetchError):
        bs.stealth_transport("http://e.com/", headers={}, timeout=5, max_bytes=100, client=client)
