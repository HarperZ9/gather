"""Launch-only, exact-origin GET grants for the read-only client profile."""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from time import monotonic

from gather.fetch import RawResponse, fetch
from gather.grants import Grants
from gather.net import decode_body, validate_public_http_url


def origin_of(url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ValueError("URL must be an explicit HTTP(S) URL without whitespace")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials and non-HTTP(S) schemes are not allowed")
    return parsed, (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80))


@dataclass(frozen=True)
class NetworkGrant:
    origins: frozenset = frozenset()
    addresses: frozenset = frozenset()

    @classmethod
    def from_launch(cls, public=(), loopback=()):
        origins, addresses = set(), set()
        for entries, local in ((public, False), (loopback, True)):
            for url in entries:
                parsed, origin = origin_of(url)
                if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                    raise ValueError("launch grants must name an origin without a path, query or fragment")
                if local:
                    if not ipaddress.ip_address(origin[1]).is_loopback:
                        raise ValueError("loopback grants require a literal loopback IP address")
                else:
                    if origin[0] != "https":
                        raise ValueError("public origins require HTTPS")
                    validate_public_http_url(url)
                infos = socket.getaddrinfo(origin[1], origin[2], type=socket.SOCK_STREAM)
                for info in infos:
                    address = ipaddress.ip_address(info[4][0])
                    if not local and not address.is_global:
                        raise ValueError("public origin must resolve only to public addresses")
                    addresses.add((str(address), origin[2]))
                origins.add(origin)
        return cls(frozenset(origins), frozenset(addresses))

    def audit_socket(self, event, args):
        if not self.origins:
            raise PermissionError("network requires a launch grant")
        if event == "socket.__new__":
            if args[1] in {socket.AF_INET, socket.AF_INET6} and args[2] == socket.SOCK_STREAM:
                return
        elif event == "socket.getaddrinfo":
            if any(args[0] == host and args[1] == port for _, host, port in self.origins):
                return
        elif event == "socket.connect":
            destination = args[1]
            if isinstance(destination, tuple) and (destination[0], destination[1]) in self.addresses:
                return
        raise PermissionError("socket operation is outside the launch grant")

    def get(self, url):
        Grants(network_sources=frozenset({"web"}) if self.origins else frozenset()).require_network("web")
        _, origin = origin_of(url)
        if origin not in self.origins:
            raise ValueError("URL origin is outside the launch grant")

        def transport(target, *, headers, timeout, max_bytes):
            # No ambient proxies, credentials, cookies or redirect authority.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            request = urllib.request.Request(target, headers=headers)
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                exc.close()
                raise ValueError(f"HTTP request refused or failed: {exc.code}") from None
            with response:
                deadline = monotonic() + 10
                body = bytearray()
                while True:
                    if monotonic() >= deadline:
                        raise ValueError("response exceeded the read time budget")
                    chunk = response.read1(min(65536, max_bytes + 1 - len(body)))
                    if not chunk:
                        if response.length not in {None, 0}:
                            raise ValueError("incomplete response; no complete receipt issued")
                        break
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError("response exceeds client byte limit; no complete receipt issued")
                return RawResponse(response.status, response.geturl(), tuple(response.headers.items()), bytes(body))

        receipt, body = fetch(url, transport=transport, max_bytes=1_000_000, timeout=10, retries=0)
        return json.dumps({"text": decode_body(body or b""), "receipt": receipt.as_dict(),
                           "authority": "explicit-launch-origin", "content_trust": "untrusted-source"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
