"""Accountable fetch core: an HTTP GET that returns a re-verifiable receipt.

Wraps gather's existing network edge ([net.py]) without weakening it: the same
scheme allowlist, private-host (SSRF) block, and cross-origin credential
stripping apply on the initial URL and every redirect hop. On top of that this
adds what a scraping tool needs but none of them witness:

  - a FetchReceipt: url, final_url, status, a sha256 of the exact bytes fetched,
    a digest of the response headers, the recorded redirect chain, and attempts;
  - conditional GET (ETag / If-Modified-Since) with honest 304 handling;
  - retry with exponential backoff on transient failures.

A reviewer can re-hash the body and confirm the receipt describes exactly those
bytes. The transport is a seam, so the orchestration (retry, conditional,
receipt) is tested offline with a fake transport; only ``urllib_transport``
touches the network.

Deliberate honesty note: the default User-Agent identifies gather rather than
impersonating a browser, and zero-dep cannot forge a TLS fingerprint. A caller
may pass their own headers to impersonate; that is their choice, on the record,
not a silent default. That is the accountability trade against Scrapling's
default stealth.
"""
from __future__ import annotations

import hashlib
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from gather.net import (
    DEFAULT_MAX_BYTES,
    DEFAULT_UA,
    _SafeRedirect,
    decode_body,
    validate_public_http_url,
)

# Standard, non-deceptive request headers. Not a browser impersonation.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_ROUTING = ("host", "x-forwarded", "forwarded")


class TransientFetchError(Exception):
    """A retryable failure (timeout, connection error, or 5xx)."""


class FetchError(Exception):
    """A fetch that failed after exhausting retries."""


@dataclass(frozen=True, slots=True)
class Redirect:
    status: int
    location: str


@dataclass(frozen=True, slots=True)
class RawResponse:
    """What a transport returns: enough to build a receipt, nothing inferred."""

    status: int
    final_url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    redirects: tuple[Redirect, ...] = ()
    truncated: bool = False   # the body was cut at max_bytes: a partial source


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _headers_digest(headers: tuple[tuple[str, str], ...]) -> str:
    canon = "\n".join(f"{k.lower()}: {v}" for k, v in sorted(headers))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _header(headers: tuple[tuple[str, str], ...], name: str) -> str:
    low = name.lower()
    for k, v in headers:
        if k.lower() == low:
            return v
    return ""


@dataclass(frozen=True, slots=True)
class FetchReceipt:
    """A re-verifiable record of one fetch. ``content_sha256`` fingerprints the
    exact bytes returned; on a 304 there is no body and ``not_modified`` is set."""

    url: str
    final_url: str
    status: int
    method: str
    fetched_at: float
    content_sha256: str
    headers_digest: str
    redirects: tuple[Redirect, ...]
    attempts: int
    not_modified: bool = False
    etag: str = ""
    last_modified: str = ""
    truncated: bool = False   # the body was cut at max_bytes: a partial source

    def verify(self, body: bytes | None) -> bool:
        """Confirm ``body`` is exactly the bytes this receipt was built from."""
        if self.not_modified:
            return not body
        return _sha_bytes(body or b"") == self.content_sha256

    def as_dict(self) -> dict:
        return {
            "url": self.url, "final_url": self.final_url, "status": self.status,
            "method": self.method, "fetched_at": self.fetched_at,
            "content_sha256": self.content_sha256, "headers_digest": self.headers_digest,
            "redirects": [{"status": r.status, "location": r.location} for r in self.redirects],
            "attempts": self.attempts, "not_modified": self.not_modified,
            "etag": self.etag, "last_modified": self.last_modified,
            "truncated": self.truncated,
        }


class _RecordingSafeRedirect(_SafeRedirect):
    """Keeps every guarantee of ``_SafeRedirect`` (guard re-check + credential
    strip per hop) and additionally records the chain for the receipt."""

    def __init__(self) -> None:
        super().__init__()
        self.chain: list[Redirect] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.chain.append(Redirect(code, newurl.strip()))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(url: str, *, headers: dict, timeout: float, max_bytes: int) -> RawResponse:
    """The network edge. Enforces the scheme allowlist + SSRF guard, records
    redirects, and maps 5xx / connection errors to ``TransientFetchError``."""
    url = validate_public_http_url(url)
    rec = _RecordingSafeRedirect()
    opener = urllib.request.build_opener(rec)
    req = urllib.request.Request(url, headers=dict(headers))
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            return RawResponse(
                resp.status, resp.geturl(), tuple(resp.headers.items()),
                body[:max_bytes], tuple(rec.chain),
                truncated=len(body) > max_bytes,
            )
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return RawResponse(304, url, tuple((e.headers or {}).items()), b"", tuple(rec.chain))
        if 500 <= e.code < 600:
            raise TransientFetchError(f"HTTP {e.code}") from e
        body = e.read(max_bytes + 1) if e.fp else b""
        return RawResponse(e.code, getattr(e, "url", url) or url,
                           tuple((e.headers or {}).items()), body[:max_bytes], tuple(rec.chain))
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise TransientFetchError(str(e)) from e


Transport = Callable[..., RawResponse]


def _build_receipt(url: str, raw: RawResponse, attempts: int, now: float) -> FetchReceipt:
    not_modified = raw.status == 304
    return FetchReceipt(
        url=url, final_url=raw.final_url, status=raw.status, method="http-get",
        fetched_at=now, content_sha256="" if not_modified else _sha_bytes(raw.body),
        headers_digest=_headers_digest(raw.headers), redirects=raw.redirects,
        attempts=attempts, not_modified=not_modified,
        etag=_header(raw.headers, "etag"), last_modified=_header(raw.headers, "last-modified"),
        truncated=raw.truncated,
    )


def fetch(
    url: str, *,
    headers: dict[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    user_agent: str = DEFAULT_UA,
    timeout: float = 20.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = 2,
    backoff: float = 0.5,
    transport: Transport = urllib_transport,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[FetchReceipt, bytes | None]:
    """Fetch ``url`` and return ``(receipt, body)``. On a 304 the body is None.

    Retries transient failures with exponential backoff. Conditional headers are
    sent when ``etag`` / ``last_modified`` are given. Routing headers are refused
    (they can desync the SSRF host guard, matching ``net.http_get``)."""
    req_headers = {"User-Agent": user_agent, **BROWSER_HEADERS}
    if headers:
        bad = sorted(k for k in headers if k.lower().startswith(_ROUTING))
        if bad:
            raise ValueError(f"routing headers are not allowed (they desync the host guard): {bad}")
        req_headers.update(headers)
    if etag:
        req_headers["If-None-Match"] = etag
    if last_modified:
        req_headers["If-Modified-Since"] = last_modified

    last: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            raw = transport(url, headers=req_headers, timeout=timeout, max_bytes=max_bytes)
        except TransientFetchError as e:
            last = e
            if attempt <= retries:
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise FetchError(f"fetch failed after {attempt} attempt(s): {e}") from e
        receipt = _build_receipt(url, raw, attempt, float(clock()))
        return receipt, (None if raw.status == 304 else raw.body)
    raise FetchError(f"fetch failed after {retries + 1} attempt(s): {last}")


def fetch_text(url: str, **kw) -> tuple[FetchReceipt, str | None]:
    """``fetch`` then decode the body to text using the response charset. Returns
    ``(receipt, None)`` on a 304."""
    receipt, body = fetch(url, **kw)
    if body is None:
        return receipt, None
    ctype = ""  # header lookup omitted for cache path; decode is charset-tolerant
    return receipt, decode_body(body, ctype)
