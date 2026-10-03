"""One HTTP request with its status and headers, for official APIs that report limits in headers.

``http_get`` in gather.net returns the body and content type and raises on an error status.
An API client that paces itself from rate-limit headers, or exchanges a token with a POST,
needs the status and headers too, including on a 429. ``http_call`` sends one request through
the same guards as ``http_get``: http and https only, no private or loopback host on the first
URL or any redirect hop, credentials dropped when a redirect changes origin, no routing headers,
and a capped body. Headers come back with lower-case names.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from gather.net import (
    DEFAULT_MAX_BYTES,
    DEFAULT_UA,
    _SafeRedirect,
    validate_public_http_url,
)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


def _check_headers(headers: dict[str, str]) -> None:
    routing = {k for k in headers if k.lower() == "host" or k.lower().startswith(("x-forwarded", "forwarded"))}
    if routing:
        raise ValueError(f"routing headers are not allowed (they can desync the host guard): {sorted(routing)}")


def http_call(url: str, *, method: str = "GET", data: bytes | None = None,
              headers: dict[str, str] | None = None, timeout: float = 20.0,
              max_bytes: int = DEFAULT_MAX_BYTES) -> Response:
    """Send one request and return its status, body and headers. An error status (4xx, 5xx)
    comes back as a Response, not an exception, so the caller can read its headers."""
    hdrs = {"User-Agent": DEFAULT_UA, **(headers or {})}
    _check_headers(hdrs)
    url = validate_public_http_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw, status, got = resp.read(max_bytes + 1), resp.status, resp.headers
    except urllib.error.HTTPError as exc:
        raw, status, got = exc.read(max_bytes + 1), exc.code, exc.headers
    if len(raw) > max_bytes:
        print(f"gather: response from {url[:60]!r} exceeded {max_bytes} bytes; truncated", file=sys.stderr)
    return Response(status, raw[:max_bytes], {k.lower(): v for k, v in (got or {}).items()})
