import pytest

from gather.net import _host_is_private, decode_body, http_get


def test_decode_body_uses_charset_from_content_type():
    assert decode_body("caf\u00e9".encode("latin-1"), "text/html; charset=latin-1") == "caf\u00e9"


def test_decode_body_handles_a_quoted_charset():
    # charset="latin-1" (quoted) is legal; the quotes must be stripped, not fed to decode
    assert decode_body("caf\u00e9".encode("latin-1"), 'text/html; charset="latin-1"') == "caf\u00e9"


def test_decode_body_defaults_to_utf8():
    assert decode_body("caf\u00e9".encode("utf-8"), "text/html") == "caf\u00e9"


def test_decode_body_falls_back_on_unknown_charset_without_raising():
    out = decode_body("caf\u00e9".encode("utf-8"), "text/html; charset=bogus-xyz")
    assert "caf" in out  # degrades to utf-8 with replacement, never raises


def test_host_is_private_blocks_internal_and_metadata_addresses():
    for host in ("127.0.0.1", "169.254.169.254", "10.0.0.1", "192.168.1.1", "localhost", "", "0.0.0.0"):
        assert _host_is_private(host) is True
    assert _host_is_private("8.8.8.8") is False  # a public literal IP is allowed


def test_http_get_refuses_non_http_schemes():
    # the network edge must not be tricked into reading local files or other schemes
    for bad in ("file:///etc/passwd", "ftp://host/x", "data:text/plain,hi"):
        with pytest.raises(ValueError):
            http_get(bad)


def test_http_get_refuses_private_hosts_before_connecting():
    # SSRF guard: a literal private/loopback/metadata host is refused with no network round-trip
    for bad in ("http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/"):
        with pytest.raises(ValueError):
            http_get(bad)


def test_http_get_refuses_routing_headers():
    # a Host / forwarding header could desync the URL-based host guard; reject before any request
    for bad in ({"Host": "internal"}, {"X-Forwarded-For": "10.0.0.1"}, {"Forwarded": "for=1.2.3.4"}):
        with pytest.raises(ValueError, match="routing headers"):
            http_get("http://example.com/", headers=bad)


def test_redirect_strips_credentials_on_cross_origin(monkeypatch):
    import urllib.request

    import gather.net as net

    monkeypatch.setattr(net, "_host_is_private", lambda h: False)  # isolate the strip logic from DNS
    handler = net._SafeRedirect()
    req = urllib.request.Request("https://api.example/data", headers={"Authorization": "Bearer secret"})
    # a cross-origin redirect (different host) must not carry the Authorization header
    new = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/collect")
    assert new is not None
    assert not any(k.lower() == "authorization" for k in new.headers)


def test_redirect_keeps_credentials_on_same_host(monkeypatch):
    import urllib.request

    import gather.net as net

    monkeypatch.setattr(net, "_host_is_private", lambda h: False)
    handler = net._SafeRedirect()
    req = urllib.request.Request("https://api.example/data", headers={"Authorization": "Bearer secret"})
    new = handler.redirect_request(req, None, 302, "Found", {}, "https://api.example/v2/data")
    assert new is not None
    assert any(k.lower() == "authorization" for k in new.headers)  # same origin: header preserved
