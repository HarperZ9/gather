import pytest

from gather.net import decode_body, http_get


def test_decode_body_uses_charset_from_content_type():
    assert decode_body("café".encode("latin-1"), "text/html; charset=latin-1") == "café"


def test_decode_body_defaults_to_utf8():
    assert decode_body("café".encode("utf-8"), "text/html") == "café"


def test_decode_body_falls_back_on_unknown_charset_without_raising():
    out = decode_body("café".encode("utf-8"), "text/html; charset=bogus-xyz")
    assert "caf" in out  # degrades to utf-8 with replacement, never raises


def test_http_get_refuses_non_http_schemes():
    # the network edge must not be tricked into reading local files or other schemes
    for bad in ("file:///etc/passwd", "ftp://host/x", "data:text/plain,hi"):
        with pytest.raises(ValueError):
            http_get(bad)
