from __future__ import annotations

import ipaddress
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

from gather import __version__

DEFAULT_UA = f"gather/{__version__} (+https://github.com/HarperZ9/gather)"
DEFAULT_MAX_BYTES = 5_000_000


def decode_body(body: bytes, content_type: str = "") -> str:
    """Decode an HTTP body to text using the charset in ``Content-Type``, defaulting utf-8.

    Pure: bytes and a header string in, text out. The charset token is unquoted (a quoted
    ``charset="latin-1"`` is legal) before use, and an unknown or absent charset falls back
    to utf-8 with replacement, so a mislabeled page degrades to readable text rather than
    raising. Tested without the network. (Feeds do not use this: XML carries its own encoding
    declaration, so feed bytes are parsed directly.)
    """
    charset = "utf-8"
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";")[0].strip().strip("\"'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _host_is_private(host: str) -> bool:
    """True if ``host`` resolves to a loopback, private, link-local, or reserved address.

    Fail-closed: an unresolvable or unparseable host is treated as private (blocked). Does a
    DNS lookup, so it belongs to the network edge. Note the residual: it resolves the name to
    check it, but urllib resolves again to connect, so a name that rebinds between the two
    lookups (DNS rebinding) is not defended here; the common metadata/loopback/private cases
    are.
    """
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
    return False


_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


def validate_public_http_url(url: str) -> str:
    """Return the trimmed URL if it is http/https and resolves to a public host, else raise
    ValueError. The reusable scheme allowlist + private-host (SSRF) guard, shared by http_get and
    the browser edge so both refuse file://, other schemes, and loopback/private/metadata hosts."""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"only http/https URLs are allowed, got: {url[:60]!r}")
    if _host_is_private(urllib.parse.urlsplit(url).hostname or ""):
        raise ValueError(f"refused: host resolves to a private or loopback address: {url[:60]!r}")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Re-applies the scheme allowlist and the private-host block to every redirect hop, and
    strips credentials when a redirect crosses origins.

    Without the first, the initial-URL scheme check buys nothing: a public URL that redirects to
    ``http://169.254.169.254/`` (cloud metadata) or a loopback/private host would be followed.
    Without the second, urllib would forward an Authorization header to whatever host a redirect
    names, so a compromised or open-redirecting endpoint could harvest a bearer token (the
    CVE-2018-18074 class). Credentials are dropped on a host change or an https-to-http downgrade.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = newurl.strip()
        if not target.lower().startswith(("http://", "https://")):
            raise urllib.error.HTTPError(newurl, code, f"refused redirect to non-http(s): {newurl[:60]!r}", headers, fp)
        if _host_is_private(urllib.parse.urlsplit(target).hostname or ""):
            raise urllib.error.HTTPError(newurl, code, f"refused redirect to private host: {newurl[:60]!r}", headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, target)
        if new is not None:
            old_u, new_u = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(target)
            cross_origin = old_u.hostname != new_u.hostname or (old_u.scheme == "https" and new_u.scheme != "https")
            if cross_origin:
                for key in [k for k in new.headers if k.lower() in _SENSITIVE_HEADERS]:
                    del new.headers[key]
        return new


def http_get(
    url: str,
    *,
    timeout: float = 20.0,
    user_agent: str = DEFAULT_UA,
    max_bytes: int = DEFAULT_MAX_BYTES,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    """GET a URL and return ``(body, content_type)``. The single network edge (urllib).

    Network access lives here and in adapter fetches, nowhere else in Gather, the
    isolated-impure-edge discipline. The scheme allowlist (http/https only) and a
    private/loopback/link-local host block are enforced on the initial URL AND on every
    redirect hop, so the guard cannot be slipped by a redirect inward (the cloud-metadata
    SSRF). Optional ``headers`` (e.g. an Authorization header) are sent but never logged: only
    the URL is, and on truncation only its first 60 chars, so put secrets in a header, not the
    URL. The body is capped at ``max_bytes``; a response that exceeds it is truncated and a
    warning is written to stderr so a short read is never mistaken for a complete one. Needs
    network; the pure ``decode_body`` and the ``_host_is_private`` check are tested directly.
    """
    url = url.strip()
    hdrs = {"User-Agent": user_agent}
    if headers:
        routing = {k for k in headers if k.lower() == "host" or k.lower().startswith(("x-forwarded", "forwarded"))}
        if routing:
            # a Host/forwarding header could steer a proxy to a target the URL-based guard never saw
            raise ValueError(f"routing headers are not allowed (they can desync the host guard): {sorted(routing)}")
        hdrs.update(headers)
    url = validate_public_http_url(url)  # scheme allowlist + private-host block (does the DNS lookup)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers=hdrs)
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
        ctype = resp.headers.get("Content-Type", "") or ""
    if len(raw) > max_bytes:
        print(f"gather: response from {url[:60]!r} exceeded {max_bytes} bytes; truncated", file=sys.stderr)
    return raw[:max_bytes], ctype
