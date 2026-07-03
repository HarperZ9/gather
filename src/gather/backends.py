"""Capability backends: the parity layer, gated and witnessed.

To match the browser-based tools without making gather depend on them, capability
is pluggable. A backend declares what it can do (execute JavaScript, impersonate
a browser at the TLS layer, parse at native speed); the registry resolves the
best available backend for a requested capability. Two rules make this honest:

  1. Missing capability -> UNVERIFIABLE, never a fake. If JavaScript rendering is
     required and no browser backend is installed, the result says UNVERIFIABLE
     with a reason. It never returns the static shell dressed up as a render.
  2. Every result records WHICH backend and capability produced it, so the
     artifact carries its own provenance: "rendered via <backend>" or
     "UNVERIFIABLE: no js-render backend".

This module is pure and stdlib-only. The heavy backends (a Playwright browser, a
TLS-impersonation transport, an lxml/selectolax fast parser) register themselves
when installed; absent, the capability is simply unmet and reported as such.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.util import find_spec

from gather.item import content_hash

CAP_FETCH = "fetch"            # basic HTTP; always available (stdlib)
CAP_JS = "js-render"          # execute JavaScript; needs a browser backend
CAP_STEALTH = "stealth"       # TLS/browser impersonation; needs a stealth transport
CAP_FAST_PARSE = "fast-parse"  # native-speed parsing; needs lxml/selectolax


@dataclass(frozen=True, slots=True)
class Backend:
    """A capability provider. ``handler(url) -> html`` does the work; ``available``
    is checked at resolve time so an optional backend only serves when installed."""

    name: str
    capabilities: frozenset[str]
    handler: Callable[[str], str] | None = None
    available: Callable[[], bool] = lambda: True


class Registry:
    """Ordered set of backends; first registered wins a capability tie."""

    def __init__(self) -> None:
        self._backends: list[Backend] = []

    def register(self, backend: Backend) -> "Registry":
        self._backends.append(backend)
        return self

    def resolve(self, capability: str) -> Backend | None:
        for b in self._backends:
            if capability in b.capabilities and b.available():
                return b
        return None

    def has(self, capability: str) -> bool:
        return self.resolve(capability) is not None

    def capabilities(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for b in self._backends:
            if b.available():
                for cap in b.capabilities:
                    out.setdefault(cap, []).append(b.name)
        return out


@dataclass(frozen=True, slots=True)
class RenderResult:
    """A capability-gated fetch/render result, carrying its own provenance."""

    url: str
    status: str          # "rendered" | "UNVERIFIABLE"
    capability: str
    backend: str
    html: str
    content_sha256: str
    reason: str = ""

    def verify(self, html: str | None = None) -> bool:
        if self.status != "rendered":
            return self.html == "" and self.content_sha256 == ""
        target = self.html if html is None else html
        return content_hash(target) == self.content_sha256

    def as_dict(self) -> dict:
        return {
            "url": self.url, "status": self.status, "capability": self.capability,
            "backend": self.backend, "content_sha256": self.content_sha256,
            "reason": self.reason,
        }


def render(url: str, *, registry: Registry, require: str = CAP_FETCH) -> RenderResult:
    """Serve ``url`` at the required capability, or return UNVERIFIABLE. Never
    fakes a capability it does not have."""
    backend = registry.resolve(require)
    if backend is None or backend.handler is None:
        return RenderResult(
            url, "UNVERIFIABLE", require, "", "", "",
            reason=f"no backend for capability {require!r}",
        )
    try:
        html = backend.handler(url)
    except Exception as e:  # capability present but failed (e.g. browser not installed)
        return RenderResult(
            url, "UNVERIFIABLE", require, backend.name, "", "",
            reason=f"{backend.name} failed: {type(e).__name__}: {e}"[:200],
        )
    return RenderResult(url, "rendered", require, backend.name, html, content_hash(html))


def detect_fast_parse() -> str | None:
    """Name of an installed native parser, or None (then stdlib is the parser)."""
    for mod in ("selectolax", "lxml"):
        if find_spec(mod) is not None:
            return mod
    return None


def best_parser(registry: Registry | None = None) -> str:
    """The parser backend in effect: a registered fast-parse backend if present,
    an installed native parser if detected, else the stdlib parser."""
    if registry is not None:
        fast = registry.resolve(CAP_FAST_PARSE)
        if fast is not None:
            return fast.name
    return detect_fast_parse() or "stdlib"


def default_registry(fetch_handler: Callable[[str], str] | None = None) -> Registry:
    """A registry with the stdlib fetch + parse capabilities always present, and
    the heavy capabilities (js-render, stealth, fast-parse) registered only if
    their optional backend is installed. Absent, those capabilities stay unmet
    and any request for them degrades to UNVERIFIABLE."""
    reg = Registry()
    reg.register(Backend("stdlib-fetch", frozenset({CAP_FETCH}), fetch_handler))
    reg.register(Backend("stdlib-parse", frozenset({"parse"})))
    fast = detect_fast_parse()
    if fast is not None:
        reg.register(Backend(fast, frozenset({CAP_FAST_PARSE, "parse"}),
                             available=lambda: find_spec(fast) is not None))
    # Optional heavy backends self-register when their dependency is present.
    try:
        from gather.backends_browser import register as _register_browser
        _register_browser(reg)
    except Exception:  # pragma: no cover - optional import
        pass
    if find_spec("curl_cffi") is not None:
        # stealth is a fetch transport, not a render handler; the marker lets
        # capabilities() report it as available.
        reg.register(Backend("curl_cffi", frozenset({CAP_STEALTH})))
    return reg
