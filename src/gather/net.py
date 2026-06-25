from __future__ import annotations

import urllib.request

DEFAULT_UA = "gather/0.3 (+https://github.com/HarperZ9/gather)"
DEFAULT_MAX_BYTES = 5_000_000


def decode_body(body: bytes, content_type: str = "") -> str:
    """Decode an HTTP body to text using the charset in ``Content-Type``, defaulting utf-8.

    Pure: bytes and a header string in, text out. Falls back to utf-8 with replacement on an
    unknown or absent charset, so a mislabeled page degrades to readable text rather than
    raising. Tested without the network.
    """
    charset = "utf-8"
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def http_get(
    url: str,
    *,
    timeout: float = 20.0,
    user_agent: str = DEFAULT_UA,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[bytes, str]:
    """GET a URL and return ``(body, content_type)``. The single network edge (urllib).

    Network access lives here and in adapter fetch methods, nowhere else in Gather, the
    isolated-impure-edge discipline. Refuses non-http(s) schemes, sends a Gather User-Agent,
    and caps the body at ``max_bytes`` so one giant response cannot exhaust memory. Needs
    network; not unit-tested against live hosts (the pure ``decode_body`` is).
    """
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"only http/https URLs are fetched, got: {url[:60]!r}")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(max_bytes + 1)[:max_bytes]
        ctype = resp.headers.get("Content-Type", "") or ""
    return body, ctype
