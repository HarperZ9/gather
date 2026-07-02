"""Accountable fetch core: receipt verification, redirects, conditional GET,
retry/backoff, and the routing-header guard. Offline via a fake transport."""
from __future__ import annotations

import hashlib

import pytest

from gather.fetch import (
    FetchError,
    RawResponse,
    Redirect,
    TransientFetchError,
    fetch,
)

BODY = b"<html><body>hi</body></html>"
OK = RawResponse(200, "http://e.com/", (("Content-Type", "text/html"), ("ETag", '"abc"')), BODY)


class FakeTransport:
    """Returns scripted outcomes (RawResponse or an Exception to raise) and
    records the headers of each call so conditional-GET can be asserted."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, timeout, max_bytes):
        self.calls.append(dict(headers))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _run(*outcomes, **kw):
    t = FakeTransport(*outcomes)
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("clock", lambda: 1.0)
    return t, fetch("http://e.com/", transport=t, **kw)


def test_200_receipt_verifies() -> None:
    _t, (rcpt, body) = _run(OK)
    assert rcpt.status == 200 and body == BODY
    assert rcpt.content_sha256 == hashlib.sha256(BODY).hexdigest()
    assert rcpt.verify(BODY) is True
    assert rcpt.attempts == 1


def test_records_redirect_chain() -> None:
    resp = RawResponse(
        200, "http://e.com/final", (("Content-Type", "text/html"),), BODY,
        (Redirect(301, "http://e.com/mid"), Redirect(302, "http://e.com/final")),
    )
    _t, (rcpt, _body) = _run(resp)
    assert [r.status for r in rcpt.redirects] == [301, 302]
    assert rcpt.final_url == "http://e.com/final"


def test_conditional_304_sends_validator_and_has_no_body() -> None:
    resp = RawResponse(304, "http://e.com/", (("ETag", '"abc"'),), b"")
    t, (rcpt, body) = _run(resp, etag='"abc"')
    assert rcpt.not_modified is True and body is None
    assert rcpt.verify(None) is True
    assert t.calls[0].get("If-None-Match") == '"abc"'


def test_retries_then_succeeds_with_backoff() -> None:
    sleeps: list[float] = []
    t = FakeTransport(TransientFetchError("boom"), TransientFetchError("boom"), OK)
    rcpt, body = fetch("http://e.com/", transport=t, sleep=sleeps.append, clock=lambda: 1.0)
    assert rcpt.attempts == 3 and body == BODY
    assert sleeps == [0.5, 1.0]  # 0.5 * 2^0, then 0.5 * 2^1


def test_retries_exhausted_raises() -> None:
    t = FakeTransport(*(TransientFetchError("x") for _ in range(3)))
    with pytest.raises(FetchError):
        fetch("http://e.com/", transport=t, retries=2, sleep=lambda s: None)


def test_tampered_body_fails_verification() -> None:
    _t, (rcpt, _body) = _run(OK)
    assert rcpt.verify(b"different bytes") is False


def test_routing_headers_refused() -> None:
    with pytest.raises(ValueError):
        fetch("http://e.com/", transport=FakeTransport(OK),
              headers={"X-Forwarded-For": "1.2.3.4"}, sleep=lambda s: None)
