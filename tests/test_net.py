import pytest

from gather.net import _host_is_private, decode_body, http_get


def test_decode_body_uses_charset_from_content_type():
    assert decode_body("café".encode("latin-1"), "text/html; charset=latin-1") == "café"


def test_decode_body_handles_a_quoted_charset():
    # charset="latin-1" (quoted) is legal; the quotes must be stripped, not fed to decode
    assert decode_body("café".encode("latin-1"), 'text/html; charset="latin-1"') == "café"


def test_decode_body_defaults_to_utf8():
    assert decode_body("café".encode("utf-8"), "text/html") == "café"


def test_decode_body_falls_back_on_unknown_charset_without_raising():
    out = decode_body("café".encode("utf-8"), "text/html; charset=bogus-xyz")
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
