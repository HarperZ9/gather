"""Dev-mode response cache: replay, revalidation, tamper detection."""
from __future__ import annotations

from gather.cache import ResponseCache, cached_fetch


class FakeReceipt:
    def __init__(self, status, etag="", last_modified="", not_modified=False):
        self.status = status
        self.etag = etag
        self.last_modified = last_modified
        self.not_modified = not_modified


def test_put_get_roundtrip_and_verify(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put("http://e.com/", status=200, body=b"<html>x</html>", etag='"v1"', fetched_at=1.0)
    got = cache.get("http://e.com/")
    assert got is not None
    entry, body = got
    assert body == b"<html>x</html>" and entry.etag == '"v1"'
    assert cache.verify("http://e.com/") is True


def test_verify_detects_tampered_body(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put("http://e.com/", status=200, body=b"orig")
    _meta, body_p = cache._paths("http://e.com/")
    body_p.write_bytes(b"tampered")
    assert cache.verify("http://e.com/") is False


def test_dev_mode_replays_without_refetching(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    calls: list[str] = []

    def ff(url, *, etag, last_modified, **kw):
        calls.append(url)
        return FakeReceipt(200, etag='"v1"'), b"<html>1</html>"

    r1, b1 = cached_fetch("http://e.com/", cache=cache, fetch_fn=ff, clock=lambda: 1.0)
    assert r1.source == "network" and b1 == b"<html>1</html>"
    r2, b2 = cached_fetch("http://e.com/", cache=cache, fetch_fn=ff, clock=lambda: 2.0)
    assert r2.source == "cache" and b2 == b"<html>1</html>"
    assert calls == ["http://e.com/"]  # fetched exactly once


def test_revalidate_304_serves_cached_body(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put("http://e.com/", status=200, body=b"<html>1</html>", etag='"v1"', fetched_at=1.0)

    def ff(url, *, etag, last_modified, **kw):
        assert etag == '"v1"'  # the stored validator is sent
        return FakeReceipt(304, not_modified=True), None

    r, b = cached_fetch("http://e.com/", cache=cache, fetch_fn=ff, revalidate=True, clock=lambda: 2.0)
    assert r.source == "cache-revalidated" and b == b"<html>1</html>"
