"""Stealth transport over curl_cffi (wedge 5, Scrapling-stealth parity).

curl_cffi impersonates a real browser's TLS/JA3 fingerprint, which gets past bot
walls that block a plain urllib client. This exposes it as an alternate transport
for the accountable fetch path, so a stealth fetch still returns the same
re-verifiable FetchReceipt (bytes hash, headers digest, redirect chain).

Safety is preserved: the scheme/SSRF guard from [net.py] is re-applied on the
initial URL and every redirect hop (redirects are followed manually, not by the
library), and credentials are stripped when a redirect crosses origins.

Optional: ``pip install 'gather-engine[stealth]'``. Absent, this transport is
simply unavailable and the stdlib fetch is used.
"""
from __future__ import annotations

from importlib.util import find_spec
from urllib.parse import urljoin, urlsplit

from gather.net import _SENSITIVE_HEADERS, validate_public_http_url

_REDIRECT_CODES = (301, 302, 303, 307, 308)


def curl_cffi_available() -> bool:
    return find_spec("curl_cffi") is not None


def _default_client():
    from curl_cffi import requests as creq  # type: ignore
    return creq


def stealth_transport(
    url: str, *, headers: dict, timeout: float, max_bytes: int,
    impersonate: str = "chrome", max_redirects: int = 10, client=None,
):
    """A fetch.Transport backed by curl_cffi. Follows redirects manually so the
    SSRF guard applies per hop; strips credentials across origins."""
    from gather.fetch import RawResponse, Redirect, TransientFetchError

    client = client or _default_client()
    current = validate_public_http_url(url)
    hdrs = dict(headers)
    origin = urlsplit(current).hostname
    chain: list = []
    try:
        for _ in range(max_redirects + 1):
            resp = client.get(current, headers=hdrs, timeout=timeout,
                              impersonate=impersonate, allow_redirects=False)
            status = resp.status_code
            location = resp.headers.get("location") or resp.headers.get("Location")
            if status in _REDIRECT_CODES and location:
                target = validate_public_http_url(urljoin(current, location))
                if urlsplit(target).hostname != origin:
                    hdrs = {k: v for k, v in hdrs.items() if k.lower() not in _SENSITIVE_HEADERS}
                    origin = urlsplit(target).hostname
                chain.append(Redirect(status, target))
                current = target
                continue
            if 500 <= status < 600:
                raise TransientFetchError(f"HTTP {status}")
            body = bytes(resp.content)[:max_bytes]
            return RawResponse(status, current, tuple(resp.headers.items()), body, tuple(chain))
        raise TransientFetchError("too many redirects")
    except TransientFetchError:
        raise
    except Exception as e:  # curl/network error -> retryable
        raise TransientFetchError(f"{type(e).__name__}: {e}") from e


def stealth_fetch(url: str, *, impersonate: str = "chrome", client=None, **fetch_kw):
    """fetch() through the stealth transport: same FetchReceipt, browser TLS."""
    from gather.fetch import fetch

    def transport(u, *, headers, timeout, max_bytes):
        return stealth_transport(u, headers=headers, timeout=timeout, max_bytes=max_bytes,
                                 impersonate=impersonate, client=client)

    return fetch(url, transport=transport, **fetch_kw)
