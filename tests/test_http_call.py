"""http_call keeps http_get's guards and returns status and headers, including on errors."""
import io
import urllib.error

import pytest

from gather import http_call as hc


class FakeResp(io.BytesIO):
    status = 200
    headers = {"X-Ratelimit-Remaining": "7"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, result):
        self.result, self.reqs = result, []

    def open(self, req, timeout):
        self.reqs.append(req)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(hc, "validate_public_http_url", lambda u: u)


def test_returns_status_body_and_lowercase_headers(monkeypatch, public):
    opener = FakeOpener(FakeResp(b"ok"))
    monkeypatch.setattr(hc.urllib.request, "build_opener", lambda *a: opener)
    resp = hc.http_call("https://api.example.org/x", method="POST", data=b"a=1", headers={"A": "b"})
    assert resp.status == 200 and resp.body == b"ok" and resp.headers == {"x-ratelimit-remaining": "7"}
    assert opener.reqs[0].get_method() == "POST" and opener.reqs[0].data == b"a=1"


def test_an_error_status_comes_back_with_its_headers(monkeypatch, public):
    err = urllib.error.HTTPError("https://api.example.org/x", 429, "Too Many", {"X-Ratelimit-Reset": "9"},
                                 io.BytesIO(b"slow down"))
    monkeypatch.setattr(hc.urllib.request, "build_opener", lambda *a: FakeOpener(err))
    resp = hc.http_call("https://api.example.org/x")
    assert resp.status == 429 and resp.headers["x-ratelimit-reset"] == "9" and resp.body == b"slow down"


def test_routing_headers_and_private_hosts_are_refused():
    with pytest.raises(ValueError, match="routing headers"):
        hc.http_call("https://api.example.org/x", headers={"Host": "169.254.169.254"})
    with pytest.raises(ValueError):
        hc.http_call("http://127.0.0.1/x")
    with pytest.raises(ValueError):
        hc.http_call("file:///etc/passwd")
