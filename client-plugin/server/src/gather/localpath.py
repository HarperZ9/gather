"""Refuse Windows network and device paths before gather opens a path it was handed.

On Windows, opening ``\\\\host\\share\\notes.md`` makes the SMB client connect to ``host`` and
authenticate as the user, which can hand the user's NTLM credentials to whoever runs ``host``.
``\\\\.\\``, ``\\\\?\\`` and ``\\??\\`` paths and reserved names such as ``CON`` or ``NUL.txt``
open devices or skip normal path handling. A research intake needs neither kind.

The check reads the text only, so a refused path never reaches the filesystem. Windows rules
apply on Windows, and on every platform to Windows-style text (a backslash or a drive prefix),
so a config gets the same answer wherever it runs. Text that starts with two separators of
either kind is refused on every platform.

On Windows, :func:`require_local` also walks the path one component at a time without following
a link. It refuses a symbolic link or junction whose target is a network or device path, before
anything opens through that link. A drive letter mapped to a share (``Z:``) looks like any
other drive, so no lexical check can see it; that stays the operator's own configuration.
"""
from __future__ import annotations

import ntpath
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass

NETWORK, DEVICE, LINK = "network", "device", "link"
FILE_SOURCES = frozenset({"docs", "pdf", "ocr", "transcribe"})
_WINDOWS = os.name == "nt"
_SEPS = "\\/"
_SPLIT = re.compile(r"[\\/]+")
_DRIVE = re.compile(r"^[A-Za-z]:")
_VOLUME = re.compile(r"^\\\\\?\\Volume\{[0-9A-Fa-f-]+\}\\?")
# Windows maps COM1-COM9 and LPT1-LPT9, and the superscript forms of 1, 2 and 3, to devices.
# COM0 and LPT0 stay ordinary file names, so refusing them would block legitimate files.
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{port}{n}" for port in ("COM", "LPT") for n in "123456789\u00b9\u00b2\u00b3"}
)
_LINK_TAGS = frozenset({getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
                        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)})
_MAX_HOPS = 40
MISSING = object()
_DETAIL = {
    NETWORK: "The path names a network location, such as a UNC path. Gather opens local paths "
             "only; copy the files to a local folder first.",
    DEVICE: "The path names a Windows device or namespace path (\\\\.\\, \\\\?\\, \\??\\, or a "
            "reserved name such as CON, NUL or COM1). Gather opens plain local paths only.",
    LINK: "The path passes through a link whose target is a network or device path, or whose "
          "target could not be read.",
}


class NonLocalPath(ValueError):
    """A path names a network location, a device, or a link to either. Raised before any open."""

    code = "NON_LOCAL_PATH"

    def __init__(self, kind: str, argument: str) -> None:
        super().__init__(f"{argument}: {_DETAIL[kind]}")
        self.kind, self.argument, self.detail = kind, argument, _DETAIL[kind]

    def payload(self) -> dict:
        return {"code": self.code, "retryable": False, "kind": self.kind,
                "argument": self.argument, "detail": self.detail}


def _windows_style(text: str) -> bool:
    return _WINDOWS or "\\" in text or bool(_DRIVE.match(text))


def _double_separator_kind(text: str) -> str | None:
    """UNC (``\\\\host``) and the ``\\\\?\\`` and ``\\\\.\\`` namespaces, with either separator."""
    if len(text) < 2 or text[0] not in _SEPS or text[1] not in _SEPS:
        return None
    head = _SPLIT.split(text[2:], maxsplit=2)
    if head[0] in (".", "?"):
        return NETWORK if len(head) > 1 and head[1].upper() == "UNC" else DEVICE
    return NETWORK


def _nt_prefix_kind(text: str) -> str | None:
    """``\\??\\C:\\x`` reaches the NT object namespace directly through the Win32 file API."""
    if len(text) >= 4 and text[0] in _SEPS and text[1:3] == "??" and text[3] in _SEPS:
        rest = _SPLIT.split(text[4:], maxsplit=1)
        return NETWORK if rest[0].upper() == "UNC" else DEVICE
    return None


def _reserved(part: str) -> bool:
    """``CON``, ``nul.txt``, ``AUX . .``, ``COM1:``: the base name before any dot or colon."""
    return part.split(".", 1)[0].split(":", 1)[0].strip(" ").upper() in _RESERVED


def classify(text: str, *, windows: bool = False) -> str | None:
    """Return NETWORK or DEVICE when ``text`` names a network or device path, else None.

    Lexical only. ``windows=True`` applies Windows rules even to POSIX-style text, for artifacts
    such as pilot manifests that must mean the same thing on every platform.
    """
    candidates = dict.fromkeys((text, text.strip()))
    for candidate in candidates:
        kind = _double_separator_kind(candidate)
        if kind:
            return kind
    if not (windows or _windows_style(text)):
        return None
    for candidate in candidates:
        kind = _nt_prefix_kind(candidate)
        if kind:
            return kind
    tail = ntpath.splitdrive(text.strip())[1]
    return DEVICE if any(_reserved(part) for part in _SPLIT.split(tail) if part) else None


def _strip_win32_prefix(text: str) -> str:
    """Map ``\\\\?\\C:\\x`` to ``C:\\x`` and ``\\\\?\\UNC\\h`` to ``\\\\h``, the forms
    ``os.readlink`` and ``os.getcwd`` can return, so they classify by what they point at."""
    for prefix in ("\\\\?\\", "\\??\\"):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            if rest[:4].upper() == "UNC\\":
                return "\\\\" + rest[4:]
            if _DRIVE.match(rest):
                return rest
    return text


_getcwd = os.getcwd


def _cwd_kind(text: str) -> str | None:
    """A relative path under a UNC or namespace working folder resolves into that location."""
    try:
        cwd = _getcwd()
    except OSError:  # the working folder is gone: a relative path cannot resolve, and open says so
        return None
    joined = ntpath.join(_strip_win32_prefix(cwd), text)
    return _double_separator_kind(joined) or _nt_prefix_kind(joined)


def require_local(value: str | os.PathLike[str], *, label: str = "path") -> str:
    """Return ``value`` as text if it names a local path; raise :class:`NonLocalPath` otherwise."""
    text = os.fspath(value)
    kind = classify(text) or (_cwd_kind(text) if _WINDOWS else None)
    if kind:
        raise NonLocalPath(kind, label)
    check_links(text, label=label)
    return text


def require_portable(value: str, *, label: str) -> str:
    """The lexical check with Windows rules on every platform, for a relative path inside a
    portable artifact such as a pilot manifest, whose meaning must not depend on the host."""
    kind = classify(value, windows=True)
    if kind:
        raise NonLocalPath(kind, label)
    return value


@dataclass(frozen=True, slots=True)
class LinkFs:
    """The two filesystem reads the link walk needs, so tests can supply a fake tree."""

    abspath: Callable[[str], str]
    link_target: Callable[[str], object]  # target text, None if not a link, MISSING; may raise LinkUnreadable


class LinkUnreadable(Exception):
    """A link's target could not be read, so the walk cannot tell where it leads."""


def _real_link_target(path: str) -> object:
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return MISSING
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in _LINK_TAGS:
        try:
            return os.readlink(path)
        except OSError as exc:
            raise LinkUnreadable(path) from exc
    return None


REAL_FS = LinkFs(abspath=ntpath.abspath, link_target=_real_link_target)


def _anchor_parts(path: str) -> tuple[str, list[str]]:
    volume = _VOLUME.match(path)
    if volume:
        anchor = volume.group(0) if volume.group(0).endswith("\\") else volume.group(0) + "\\"
        return anchor, [p for p in _SPLIT.split(path[volume.end():]) if p]
    drive, tail = ntpath.splitdrive(path)
    return drive + "\\", [p for p in _SPLIT.split(tail) if p]


def _follow(parent: str, raw: str, rest: list[str], label: str) -> tuple[str, list[str]]:
    target = _strip_win32_prefix(raw)
    if _VOLUME.match(target):  # a folder mounted from another local volume
        anchor, parts = _anchor_parts(target)
        return anchor, parts + rest
    joined = ntpath.normpath(ntpath.join(parent, target))
    if classify(target, windows=True) or classify(joined, windows=True):
        raise NonLocalPath(LINK, label)
    anchor, parts = _anchor_parts(joined)
    return anchor, parts + rest


def check_links(path: str, *, label: str = "path", fs: LinkFs | None = None) -> None:
    """Walk ``path`` from its root without following a link, and refuse a link whose target is a
    network or device path. A relative target resolves from the link's own folder. The walk stops
    at the first missing component, since nothing past it can be opened. Without ``fs`` it runs on
    Windows only: a POSIX link cannot open an SMB session by its target text."""
    if fs is None and not _WINDOWS:
        return
    fs = fs or REAL_FS
    full = _strip_win32_prefix(fs.abspath(path))  # a long-path working folder keeps its prefix
    kind = classify(full, windows=True)
    if kind:
        raise NonLocalPath(kind, label)
    anchor, parts = _anchor_parts(full)
    hops = 0
    while parts:
        here = ntpath.join(anchor, parts[0])
        try:
            target = fs.link_target(here)
        except LinkUnreadable as exc:
            raise NonLocalPath(LINK, label) from exc
        if target is MISSING:
            return
        if target is None:
            anchor, parts = here, parts[1:]
            continue
        hops += 1
        if hops > _MAX_HOPS:
            raise NonLocalPath(LINK, label)
        anchor, parts = _follow(anchor, str(target), parts[1:], label)


def check_entry(path: str, *, label: str) -> None:
    """Check one entry found by a directory walk: its own name, and on Windows the link it may be.
    Only the entry is new; the walk's root and its parent folders were checked already."""
    kind = classify(path)
    if kind:
        raise NonLocalPath(kind, label)
    if not _WINDOWS:
        return
    try:
        target = REAL_FS.link_target(path)
    except LinkUnreadable as exc:
        raise NonLocalPath(LINK, label) from exc
    if isinstance(target, str):
        check_links(path, label=label)


def check_run_paths(cfg: Mapping[str, object], *, operator: bool) -> None:
    """Refuse a run config's file-source targets on every surface, and its ``store`` when the
    config did not come from the operator (the MCP surface), before any job runs."""
    jobs = cfg.get("jobs")
    for index, job in enumerate(jobs if isinstance(jobs, list) else []):
        if isinstance(job, Mapping) and job.get("source") in FILE_SOURCES:
            target = job.get("target")
            if isinstance(target, str):
                require_local(target, label=f"jobs[{index}].target")
    store = cfg.get("store")
    if not operator and isinstance(store, str) and store:
        require_local(store, label="store")
