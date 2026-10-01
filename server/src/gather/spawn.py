"""The one way Gather starts a child program: through the vendored safe_spawn helper.

Every external tool (``pdftotext``, ``yt-dlp``, ``tesseract``, ``whisper``, a Chromium-family
browser) and every operator-configured command (a synthesizer or provenance edge) starts here.
The helper resolves the program to an absolute path, starts it in a new private empty folder,
and hands it an environment allowlist instead of Gather's whole environment. The PATH lookup
skips relative and empty entries and every entry that reaches the caller's folder (the folder
itself, a folder below it, a link to either, or another spelling). The child's PATH keeps only
what the lookup keeps, so the child's own lookups skip the same entries. Two cases narrow the
guard. At a filesystem root, or at or above the home folder, only an entry naming that folder
itself leaves, because installed tools live below it. A caller's folder that is the
interpreter's folder or, on Windows, the Windows, System32 or SysWOW64 folder guards nothing,
because Gather already runs code from there. Output stays bytes, exactly as the tool wrote it,
so receipts hash the same text they always did.

Launch configuration the operator controls:

- ``GATHER_<TOOL>`` (``GATHER_PDFTOTEXT``, ``GATHER_YT_DLP``, ``GATHER_TESSERACT``,
  ``GATHER_WHISPER``, ``GATHER_CHROMIUM``): an absolute path that wins over the PATH lookup.
- ``GATHER_CHILD_ENV``: extra variable names a child may see, comma-separated (for example a
  synthesizer's API key). Nothing else from Gather's environment reaches a child.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence

from gather._vendor import safe_spawn

CHILD_ENV_VAR = "GATHER_CHILD_ENV"
OVERRIDES = {
    "pdftotext": "GATHER_PDFTOTEXT",
    "yt-dlp": "GATHER_YT_DLP",
    "tesseract": "GATHER_TESSERACT",
    "whisper": "GATHER_WHISPER",
    "chromium": "GATHER_CHROMIUM",
}
# Network tools keep the proxy and CA settings they need to reach the network at all.
NETWORK_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
               "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR")
_UNAVAILABLE = frozenset({"NOT_FOUND", "BAD_OVERRIDE", "BAD_PATH", "UNAVAILABLE"})


class ToolUnavailable(FileNotFoundError):
    """The tool could not be found or started. ``filename`` is the name asked for, never a path."""


class ToolRefused(RuntimeError):
    """The helper refused to start the tool (for example, cmd.exe metacharacters for a batch file)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _extra_env() -> tuple[str, ...]:
    return tuple(n.strip() for n in os.environ.get(CHILD_ENV_VAR, "").split(",") if n.strip())


def _bytes_runner(argv, input=None, timeout=None, cwd=None, env=None):  # type: ignore[no-untyped-def]
    """safe_spawn.bounded_run with bytes in and out: no decoding, no newline translation."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, env=env,
                            start_new_session=os.name != "nt")
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        safe_spawn._stop_tree(proc)
        try:
            proc.communicate(timeout=safe_spawn.DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            pass  # the tree is already killed; the caller gets the original timeout either way
        raise subprocess.TimeoutExpired(os.path.basename(argv[0]), timeout) from None
    except BaseException:
        safe_spawn._stop_tree(proc)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run_tool(name: str, args: Sequence[str], *, timeout: float, input: bytes | None = None,
             network: bool = False) -> subprocess.CompletedProcess:
    """Start ``name`` with ``args`` through safe_spawn and return its bytes result.

    ``name`` is a bare program name (looked up on the absolute PATH entries, after its
    ``GATHER_<TOOL>`` override) or an absolute path. Raises ToolUnavailable when the program is
    missing or cannot start, ToolRefused when the helper refuses the arguments, and
    subprocess.TimeoutExpired after stopping the whole process tree.
    """
    allow = _extra_env() + (NETWORK_ENV if network else ())
    try:
        return safe_spawn.run(name, list(args), override_var=OVERRIDES.get(name), input=input,
                              timeout=timeout, allow_env=allow, runner=_bytes_runner)
    except safe_spawn.SpawnRefused as exc:
        if exc.code in _UNAVAILABLE:
            raise ToolUnavailable(2, str(exc), os.path.basename(name)) from None
        raise ToolRefused(exc.code, str(exc)) from None


def find_tool(name: str) -> str | None:
    """The absolute path ``run_tool(name, ...)`` would start, or None when it finds none.

    The same guarded lookup: the ``GATHER_<TOOL>`` override first, then the absolute PATH
    entries that do not reach the working folder. A child's own lookup of ``name`` walks that
    same PATH, so this also answers whether a child could start ``name`` itself (yt-dlp and its
    JavaScript runtime, say). A copy in the working folder never counts as found.
    """
    try:
        return safe_spawn.resolve(name, OVERRIDES.get(name))
    except safe_spawn.SpawnRefused:
        return None
