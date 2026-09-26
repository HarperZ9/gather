"""Launch-only grants for the MCP surface.

A gather.run config or a pilot manifest can arrive from tool arguments, so a model (or text a
model was asked to read) controls it. Anything in it that runs a command, reaches the network or
sends a credential needs a grant the operator set when launching the server:

- ``GATHER_ALLOW_EXEC`` (or ``gather mcp --allow-exec``): the commands a config may run as its
  ``synthesizer`` or ``provenance`` edge, matched against the command's first element, and the
  browser executables a pilot manifest may name.
- ``GATHER_ALLOW_NETWORK`` (or ``--allow-network``): the network sources a config or a live
  pilot manifest may use, by source name, or ``all``.
- ``GATHER_AUTH_ENV_ALLOW`` (or ``--auth-env``): ``NAME@host`` pairs. The ``api`` source may read
  the variable NAME only to send it to that exact host.

The grant is read once, when the server starts. Arguments can narrow it and never widen it:
nothing in a config, a manifest or a tool call is read as a grant. The CLI and the Python API run
the operator's own config and keep full trust (:data:`OPERATOR`).
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

NETWORK_SOURCES = frozenset({"web", "feed", "arxiv", "scholar", "video", "api", "browser"})
DEFAULT_BROWSER = "chromium"
DEFAULT_AUTH_ENV = "GATHER_API_TOKEN"
EXEC_VAR, NETWORK_VAR, AUTH_VAR = "GATHER_ALLOW_EXEC", "GATHER_ALLOW_NETWORK", "GATHER_AUTH_ENV_ALLOW"
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_DETAIL = {
    EXEC_VAR: "The request names a command to run. The server was not launched with a grant "
              "naming that command.",
    NETWORK_VAR: "The request names a network source. The server was not launched with a grant "
                 "for that source.",
    AUTH_VAR: "The request names a credential variable for a host. The server was not launched "
              "with a grant binding that variable to that host.",
}


class GrantRequired(Exception):
    """A request needs a launch grant it does not have. ``setup`` names the variable to set."""

    code = "GRANT_REQUIRED"

    def __init__(self, setup: str) -> None:
        super().__init__(_DETAIL[setup])
        self.setup = setup
        self.detail = _DETAIL[setup]

    def payload(self) -> dict:
        return {"code": self.code, "retryable": False, "setup": self.setup, "detail": self.detail}


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _auth_pairs(entries: Iterable[str]) -> frozenset[tuple[str, str]]:
    pairs = set()
    for entry in entries:
        name, sep, host = entry.partition("@")
        name, host = name.strip(), host.strip().lower()
        if not sep or not host or not _ENV_NAME.match(name) or "/" in host or ":" in host:
            # the entry is not printed: it is launch config, but it may be a mistyped value
            print(f"gather: an {AUTH_VAR} entry is not NAME@host and was ignored", file=sys.stderr)
            continue
        pairs.add((name, host))
    return frozenset(pairs)


def _network(entries: Iterable[str]) -> frozenset[str]:
    names = {e.lower() for e in entries}
    if names & {"all", "1", "true", "yes"}:
        return NETWORK_SOURCES
    return frozenset(names & NETWORK_SOURCES)


@dataclass(frozen=True, slots=True)
class Grants:
    exec_commands: frozenset[str] = frozenset()
    network_sources: frozenset[str] = frozenset()
    auth_env: frozenset[tuple[str, str]] = frozenset()
    operator: bool = False

    @classmethod
    def from_launch(cls, environ: Mapping[str, str] | None = None, *, exec_commands: Iterable[str] = (),
                    network: Iterable[str] = (), auth_env: Iterable[str] = ()) -> Grants:
        env = os.environ if environ is None else environ
        return cls(
            exec_commands=frozenset([*_split(env.get(EXEC_VAR)), *(c.strip() for c in exec_commands if c.strip())]),
            network_sources=_network([*_split(env.get(NETWORK_VAR)), *network]),
            auth_env=_auth_pairs([*_split(env.get(AUTH_VAR)), *auth_env]),
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Grants:
        return cls.from_launch(environ)

    def allows_command(self, command: str) -> bool:
        if self.operator:
            return True
        norm = os.path.normcase
        return any(norm(command) == norm(allowed) for allowed in self.exec_commands)

    def require_command(self, command: object) -> None:
        if self.operator:
            return  # the operator's own config: shape errors are reported by the config loader
        if not (isinstance(command, str) and command and self.allows_command(command)):
            raise GrantRequired(EXEC_VAR)

    def require_network(self, source: str) -> None:
        if source in NETWORK_SOURCES and not (self.operator or source in self.network_sources):
            raise GrantRequired(NETWORK_VAR)

    def require_credential(self, name: object, url: object) -> None:
        if self.operator:
            return
        parts = urllib.parse.urlsplit(url.strip()) if isinstance(url, str) else None
        host = parts.hostname if parts is not None and parts.scheme.lower() == "https" else None
        if not isinstance(name, str) or not host or (name, host.lower()) not in self.auth_env:
            raise GrantRequired(AUTH_VAR)  # a credential travels only over https to its bound host


OPERATOR = Grants(operator=True)
NONE = Grants()


def check_run_config(cfg: Mapping[str, object], grants: Grants) -> None:
    """Raise GrantRequired before anything runs if ``cfg`` needs a grant ``grants`` lacks."""
    jobs = cfg.get("jobs")
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, Mapping):
            continue
        source = job.get("source")
        if isinstance(source, str):
            grants.require_network(source)
            if source == "api":
                grants.require_credential(job.get("auth_env", DEFAULT_AUTH_ENV), job.get("target"))
    for key in ("synthesizer", "provenance"):
        command = cfg.get(key)
        if command:
            grants.require_command(command[0] if isinstance(command, list) and command else None)


def check_pilot_manifest(manifest: object, grants: Grants) -> None:
    """The same check for a validated pilot manifest (``gather.pilot_manifest.PilotManifest``)."""
    if getattr(manifest, "mode", None) != "live":
        return  # offline manifests replay local fixtures only
    for mission in getattr(manifest, "missions", ()):
        for source in mission.sources:
            grants.require_network(source.adapter)
            if source.adapter == "api":
                grants.require_credential(source.options.get("auth_env", DEFAULT_AUTH_ENV), source.target)
            if source.adapter == "browser":
                browser = source.options.get("browser", DEFAULT_BROWSER)
                if browser != DEFAULT_BROWSER or source.options.get("no_sandbox", False) is not False:
                    grants.require_command(browser)  # another executable, or the sandbox turned off
