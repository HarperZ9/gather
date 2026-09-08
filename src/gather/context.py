from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from gather.availability import assess_availability
from gather.digest import digest_of_receipts
from gather.item import content_hash
from gather.store import CORRUPT, MATCH, MISSING, Corpus, verify_stored_text

INSPECT_SCHEMA = "gather.readable-corpus/v1"
CONTEXT_SCHEMA = "gather.readable-context/v1"
VIEW_CODEC = "utf8-crlf-cr-to-lf/v1"
DEFAULT_EXCERPT_CHARS = 600
DEFAULT_SELECTION_CHARS = 1200
DEFAULT_MAX_ROWS = 12
DEFAULT_MAX_TOTAL_CHARS = 12_000
DEFAULT_MAX_CATALOG_BYTES = 5_000_000
DEFAULT_MAX_CATALOG_ROWS = 10_000
DEFAULT_MAX_BODY_BYTES = 5_000_000
DEFAULT_MAX_READ_BYTES = 10_000_000
HARD_MAX_ROWS = 50
HARD_MAX_CHARS = 100_000
HARD_MAX_BYTES = 100_000_000
HARD_MAX_CATALOG_ROWS = 100_000
UNSAFE_PATH = "UNSAFE_PATH"
BODY_OVERSIZE = "BODY_OVERSIZE"
READ_BUDGET_EXHAUSTED = "READ_BUDGET_EXHAUSTED"
_BODY_STATUSES = {MATCH, MISSING, CORRUPT, UNSAFE_PATH, BODY_OVERSIZE, READ_BUDGET_EXHAUSTED}

_DOES_NOT_PROVE = [
    "truth of selected source claims",
    "claim support or contradiction",
    "completeness of gathered coverage",
    "that a downstream model used this context correctly",
]
_HEX = set("0123456789abcdef")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CHUNK = 64 * 1024


class _WindowsCtypesModule(Protocol):
    def get_last_error(self) -> int: ...


class _WindowsMsvcrtModule(Protocol):
    def get_osfhandle(self, fd: int, /) -> int: ...

    def open_osfhandle(self, handle: int, flags: int, /) -> int: ...


@dataclass
class _ReadBudget:
    remaining: int
    limit: int

    def consume(self, amount: int) -> bool:
        if amount > self.remaining:
            return False
        self.remaining -= amount
        return True


@dataclass(frozen=True)
class _BodyRead:
    status: str
    text: str | None = None
    sha256: str = ""
    bytes_read: int = 0
    max_body_bytes: int | None = None
    max_read_bytes: int | None = None
    source_text: str | None = None
    source_sha256: str = ""
    view_sha256: str = ""
    storage: dict[str, str] | None = None
    storage_status: str = ""
    storage_witnessed: bool = False


class _ReadFailure(Exception):
    def __init__(self, status: str, *, bytes_read: int = 0) -> None:
        super().__init__(status)
        self.status = status
        self.bytes_read = bytes_read


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _hex_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX for c in value):
        raise ValueError(f"{name} must be a sha256 hex digest")
    return value


def _cap(value: object | None, default: int, name: str, *, hard: int) -> int:
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    if value > hard:
        raise ValueError(f"{name} must be <= {hard}")
    return value


def _as_corpus(corpus: Corpus | str | os.PathLike[str]) -> Corpus:
    if isinstance(corpus, Corpus):
        return corpus
    return Corpus(os.fspath(corpus))


def _corpus_root(corpus: Corpus) -> Path:
    root = getattr(corpus, "_root", None)
    if not isinstance(root, str) or not root:
        raise ValueError("corpus root is unavailable")
    return Path(root)


def _list_field(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _row_identity(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": row.get("kind", ""),
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "source": row.get("source", ""),
        "ref": row.get("ref", ""),
        "method": row.get("method", ""),
        "sha256": row.get("sha256", ""),
        "derived_from": _list_field(row.get("derived_from")),
    }


def row_ref(row: Mapping[str, object]) -> str:
    """Return the stable selector for one catalog row without reading its body."""
    return "row_" + _sha(_row_identity(row))[:32]


_UNSAFE_ERRNOS = {
    errno.ELOOP,
    errno.ENOTDIR,
}
if hasattr(errno, "EFTYPE"):
    _UNSAFE_ERRNOS.add(errno.EFTYPE)


class _MissingPath(Exception):
    pass


def _safe_part(part: str) -> bool:
    if not isinstance(part, str) or part in {"", ".", ".."}:
        return False
    if "/" in part or "\\" in part or "\x00" in part:
        return False
    # A colon can name an alternate data stream on Windows. The content-addressed
    # store never needs it, so reject it before it reaches a native open call.
    return ":" not in part


def _normalize_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _windows_kernel32():
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True)


def _windows_ntdll():
    import ctypes

    return ctypes.WinDLL("ntdll", use_last_error=True)


def _windows_raise_last_error(message: str) -> None:
    import ctypes

    win_ctypes = cast(_WindowsCtypesModule, ctypes)
    raise ValueError(f"{message}: {win_ctypes.get_last_error()}")


def _windows_ntstatus(status: int) -> int:
    value = int(status)
    if value < 0:
        value += 1 << 32
    return value


def _windows_final_path_from_handle(handle: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    get_final = kernel32.GetFinalPathNameByHandleW
    get_final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final.restype = wintypes.DWORD
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    result = get_final(wintypes.HANDLE(handle), buffer, size, 0)
    if result == 0 or result >= size:
        _windows_raise_last_error("cannot resolve final corpus path from handle")
    return _normalize_windows_handle_path(buffer.value)


def _windows_final_path_from_fd(fd: int) -> str:
    import msvcrt

    win_msvcrt = cast(_WindowsMsvcrtModule, msvcrt)
    return _windows_final_path_from_handle(win_msvcrt.get_osfhandle(fd))


def _assert_windows_fd_final_path(fd: int, expected_final_path: str, *, bytes_read: int = 0) -> None:
    actual = _windows_final_path_from_fd(fd)
    if actual != expected_final_path:
        raise _ReadFailure(UNSAFE_PATH, bytes_read=bytes_read)


def _windows_close_handle(handle: int) -> None:
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(wintypes.HANDLE(handle))


def _windows_handle_attributes(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    info = BY_HANDLE_FILE_INFORMATION()
    get_info = _windows_kernel32().GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]
    get_info.restype = wintypes.BOOL
    if not get_info(wintypes.HANDLE(handle), ctypes.byref(info)):
        _windows_raise_last_error("cannot inspect corpus handle")
    return int(info.dwFileAttributes)


def _windows_validate_directory_handle(handle: int) -> None:
    attrs = _windows_handle_attributes(handle)
    if attrs & _REPARSE_POINT:
        raise _ReadFailure(UNSAFE_PATH)
    if not attrs & stat.FILE_ATTRIBUTE_DIRECTORY:
        raise _ReadFailure(UNSAFE_PATH)


def _windows_validate_file_handle(handle: int) -> None:
    attrs = _windows_handle_attributes(handle)
    if attrs & _REPARSE_POINT:
        raise _ReadFailure(UNSAFE_PATH)
    if attrs & stat.FILE_ATTRIBUTE_DIRECTORY:
        raise _ReadFailure(UNSAFE_PATH)


def _windows_createfile_root(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x00000001 | 0x00000080 | 0x00100000,  # FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE
        0x00000001,  # FILE_SHARE_READ, deliberately excluding FILE_SHARE_DELETE during the operation
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    if handle in (0, ctypes.c_void_p(-1).value):
        _windows_raise_last_error("cannot open corpus root handle")
    return int(handle)


def _windows_unicode_string(value: str):
    import ctypes
    from ctypes import wintypes

    ushort = getattr(wintypes, "USHORT", ctypes.c_ushort)

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", ushort),
            ("MaximumLength", ushort),
            ("Buffer", wintypes.LPWSTR),
        ]

    buffer = ctypes.create_unicode_buffer(value)
    encoded_len = len(value.encode("utf-16-le"))
    return UNICODE_STRING(encoded_len, encoded_len + 2, ctypes.cast(buffer, wintypes.LPWSTR)), buffer


def _windows_nt_create_child(parent_handle: int, component: str, *, directory: bool, missing_ok: bool = False) -> int | None:
    import ctypes
    from ctypes import wintypes

    if not _safe_part(component):
        raise ValueError("corpus path contains an unsafe relative component")

    class OBJECT_ATTRIBUTES(ctypes.Structure):
        pass

    class IO_STATUS_BLOCK(ctypes.Structure):
        _fields_ = [
            ("Status", ctypes.c_void_p),
            ("Information", ctypes.c_size_t),
        ]

    unicode_name, _name_buffer = _windows_unicode_string(component)
    OBJECT_ATTRIBUTES._fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.c_void_p),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]
    attrs = OBJECT_ATTRIBUTES(
        ctypes.sizeof(OBJECT_ATTRIBUTES),
        wintypes.HANDLE(parent_handle),
        ctypes.cast(ctypes.pointer(unicode_name), ctypes.c_void_p),
        0x00000040,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    create_file = _windows_ntdll().NtCreateFile
    create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(OBJECT_ATTRIBUTES),
        ctypes.POINTER(IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    create_file.restype = wintypes.LONG
    desired_access = 0x00000080 | 0x00100000  # FILE_READ_ATTRIBUTES | SYNCHRONIZE
    if directory:
        desired_access |= 0x00000001  # FILE_LIST_DIRECTORY
    else:
        desired_access |= 0x00000001 | 0x00000008  # FILE_READ_DATA | FILE_READ_EA
    options = 0x00200000 | 0x00000020  # FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT
    options |= 0x00000001 if directory else 0x00000040  # FILE_DIRECTORY_FILE / FILE_NON_DIRECTORY_FILE
    status = create_file(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attrs),
        ctypes.byref(io_status),
        None,
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        0x00000001,  # FILE_SHARE_READ, no delete sharing while the authority is live
        1,  # FILE_OPEN
        options,
        None,
        0,
    )
    code = _windows_ntstatus(status)
    if code == 0:
        if handle.value is None:
            raise ValueError("NtCreateFile returned success without a handle")
        return int(handle.value)
    if missing_ok and code in {0xC0000034, 0xC000003A, 0xC000000F}:  # NAME_NOT_FOUND/PATH_NOT_FOUND/NO_SUCH_FILE
        return None
    if code in {0xC0000103, 0xC00000BA}:  # NOT_A_DIRECTORY / FILE_IS_A_DIRECTORY
        raise _ReadFailure(UNSAFE_PATH)
    raise ValueError(f"cannot open confined corpus path component {component!r}: NTSTATUS 0x{code:08x}")


def _windows_handle_to_fd(handle: int) -> int:
    import msvcrt

    # open_osfhandle transfers ownership only on success. On failure the caller
    # still owns the native handle and must close it exactly once.
    win_msvcrt = cast(_WindowsMsvcrtModule, msvcrt)
    return win_msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))


def _required_os_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int):
        raise ValueError(f"confined corpus reads require {name} support on this platform")
    return value


def _read_open_fd_bytes(
    fd: int,
    *,
    max_bytes: int,
    budget: _ReadBudget | None,
    expected_final_path: str | None = None,
) -> bytes:
    if expected_final_path is not None:
        _assert_windows_fd_final_path(fd, expected_final_path)
    fd_stat = os.fstat(fd)
    if not stat.S_ISREG(fd_stat.st_mode):
        raise _ReadFailure(UNSAFE_PATH)
    expected_size = fd_stat.st_size
    if expected_size > max_bytes:
        raise _ReadFailure(BODY_OVERSIZE)
    if budget is not None and expected_size > budget.remaining:
        raise _ReadFailure(READ_BUDGET_EXHAUSTED)
    chunks: list[bytes] = []
    total = 0
    while total < expected_size:
        request = min(_CHUNK, expected_size - total, max_bytes - total)
        if budget is not None:
            request = min(request, budget.remaining)
        if request <= 0:
            status = BODY_OVERSIZE if total >= max_bytes else READ_BUDGET_EXHAUSTED
            raise _ReadFailure(status, bytes_read=total)
        chunk = os.read(fd, request)
        if budget is not None and not budget.consume(len(chunk)):
            raise _ReadFailure(READ_BUDGET_EXHAUSTED, bytes_read=total)
        total += len(chunk)
        if not chunk:
            break
        chunks.append(chunk)
    after_stat = os.fstat(fd)
    if expected_final_path is not None:
        _assert_windows_fd_final_path(fd, expected_final_path, bytes_read=total)
    if total != expected_size or after_stat.st_size != expected_size:
        if after_stat.st_size > max_bytes:
            raise _ReadFailure(BODY_OVERSIZE, bytes_read=total)
        if budget is not None and after_stat.st_size > total + budget.remaining:
            raise _ReadFailure(READ_BUDGET_EXHAUSTED, bytes_read=total)
        raise _ReadFailure(CORRUPT, bytes_read=total)
    return b"".join(chunks)


class _CorpusAuthority:
    """Operation-scoped authority for catalog and body reads under one corpus root."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.root = _corpus_root(corpus)
        self._missing_root = False
        self._win_dirs: dict[tuple[str, ...], int] = {}
        self._posix_dirs: dict[tuple[str, ...], int] = {}

    def __enter__(self) -> _CorpusAuthority:
        if not os.path.lexists(self.root):
            self._missing_root = True
            return self
        if os.name == "nt":
            handle = _windows_createfile_root(self.root)
            try:
                _windows_validate_directory_handle(handle)
            except _ReadFailure as exc:
                _windows_close_handle(handle)
                raise ValueError(f"cannot safely open corpus root: {exc.status}") from exc
            except Exception:
                _windows_close_handle(handle)
                raise
            self._win_dirs[()] = handle
            return self
        self._posix_enter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for parts, handle in sorted(self._win_dirs.items(), key=lambda item: len(item[0]), reverse=True):
            _windows_close_handle(handle)
        self._win_dirs.clear()
        for parts, fd in sorted(self._posix_dirs.items(), key=lambda item: len(item[0]), reverse=True):
            os.close(fd)
        self._posix_dirs.clear()

    def read_bytes(
        self,
        parts: Sequence[str],
        *,
        max_bytes: int,
        budget: _ReadBudget | None = None,
        missing_ok: bool = False,
    ) -> bytes | None:
        if any(not _safe_part(part) for part in parts):
            raise ValueError("corpus path contains an unsafe relative component")
        if self._missing_root:
            if missing_ok:
                return None
            raise ValueError("corpus root is missing")
        try:
            if os.name == "nt":
                return self._read_bytes_windows(tuple(parts), max_bytes=max_bytes, budget=budget, missing_ok=missing_ok)
            return self._read_bytes_posix(tuple(parts), max_bytes=max_bytes, budget=budget, missing_ok=missing_ok)
        except _MissingPath:
            if missing_ok:
                return None
            raise

    def _posix_enter(self) -> None:
        if os.open not in os.supports_dir_fd:
            raise ValueError("confined corpus reads require POSIX openat support on this platform")
        dir_flags = (
            os.O_RDONLY
            | _required_os_flag("O_DIRECTORY")
            | _required_os_flag("O_NOFOLLOW")
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            fd = os.open(self.root, dir_flags)
        except OSError as exc:
            if exc.errno in _UNSAFE_ERRNOS:
                raise ValueError("cannot safely open corpus root: UNSAFE_PATH") from exc
            raise
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise ValueError("cannot safely open corpus root: UNSAFE_PATH")
        except Exception:
            os.close(fd)
            raise
        self._posix_dirs[()] = fd

    def _posix_dir_fd(self, parts: tuple[str, ...], *, missing_ok: bool) -> int | None:
        if parts in self._posix_dirs:
            return self._posix_dirs[parts]
        parent = self._posix_dir_fd(parts[:-1], missing_ok=missing_ok)
        if parent is None:
            return None
        dir_flags = (
            os.O_RDONLY
            | _required_os_flag("O_DIRECTORY")
            | _required_os_flag("O_NOFOLLOW")
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            fd = os.open(parts[-1], dir_flags, dir_fd=parent)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise _MissingPath from None
        except OSError as exc:
            if exc.errno in _UNSAFE_ERRNOS:
                raise _ReadFailure(UNSAFE_PATH) from exc
            raise
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise _ReadFailure(UNSAFE_PATH)
        except Exception:
            os.close(fd)
            raise
        self._posix_dirs[parts] = fd
        return fd

    def _read_bytes_posix(
        self,
        parts: tuple[str, ...],
        *,
        max_bytes: int,
        budget: _ReadBudget | None,
        missing_ok: bool,
    ) -> bytes | None:
        parent = self._posix_dir_fd(parts[:-1], missing_ok=missing_ok)
        if parent is None:
            return None
        file_flags = (
            os.O_RDONLY
            | _required_os_flag("O_NOFOLLOW")
            | _required_os_flag("O_NONBLOCK")
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            fd = os.open(parts[-1], file_flags, dir_fd=parent)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise _MissingPath from None
        except OSError as exc:
            if exc.errno in _UNSAFE_ERRNOS:
                raise _ReadFailure(UNSAFE_PATH) from exc
            raise
        try:
            return _read_open_fd_bytes(fd, max_bytes=max_bytes, budget=budget)
        finally:
            os.close(fd)

    def _windows_dir_handle(self, parts: tuple[str, ...], *, missing_ok: bool) -> int | None:
        if parts in self._win_dirs:
            return self._win_dirs[parts]
        parent = self._windows_dir_handle(parts[:-1], missing_ok=missing_ok)
        if parent is None:
            return None
        handle = _windows_nt_create_child(parent, parts[-1], directory=True, missing_ok=missing_ok)
        if handle is None:
            return None
        try:
            _windows_validate_directory_handle(handle)
        except Exception:
            _windows_close_handle(handle)
            raise
        self._win_dirs[parts] = handle
        return handle

    def _read_bytes_windows(
        self,
        parts: tuple[str, ...],
        *,
        max_bytes: int,
        budget: _ReadBudget | None,
        missing_ok: bool,
    ) -> bytes | None:
        parent = self._windows_dir_handle(parts[:-1], missing_ok=missing_ok)
        if parent is None:
            return None
        handle = _windows_nt_create_child(parent, parts[-1], directory=False, missing_ok=missing_ok)
        if handle is None:
            return None
        fd: int | None = None
        try:
            _windows_validate_file_handle(handle)
            parent_final = _windows_final_path_from_handle(parent)
            expected_final_path = _normalize_windows_handle_path(os.path.join(parent_final, parts[-1]))
            fd = _windows_handle_to_fd(handle)
            handle = 0
            return _read_open_fd_bytes(fd, max_bytes=max_bytes, budget=budget, expected_final_path=expected_final_path)
        finally:
            if fd is not None:
                os.close(fd)
            elif handle:
                _windows_close_handle(handle)


def _load_catalog_rows(
    authority: _CorpusAuthority,
    *,
    max_catalog_bytes: int,
    max_catalog_rows: int,
) -> list[dict]:
    try:
        raw = authority.read_bytes(
            ("catalog.jsonl",),
            max_bytes=max_catalog_bytes,
            missing_ok=True,
        )
    except _ReadFailure as exc:
        if exc.status == BODY_OVERSIZE:
            raise ValueError(f"corpus catalog exceeds max_catalog_bytes ({max_catalog_bytes})") from exc
        raise ValueError(f"cannot safely read corpus catalog: {exc.status}") from exc
    except ValueError as exc:
        raise ValueError(f"cannot safely read corpus catalog: {exc}") from exc
    if raw is None:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("corpus catalog is not valid UTF-8") from exc
    rows: list[dict] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if len(rows) >= max_catalog_rows:
            raise ValueError(f"corpus catalog has more than {max_catalog_rows} row(s)")
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"corpus catalog line {line_number} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"corpus catalog line {line_number} is not a JSON object")
        rows.append(value)
    return rows


def _view_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _corpus_digest_version(rows: Sequence[Mapping[str, object]]) -> str:
    return "storage-witnessed/v1" if any(row.get("storage") is not None for row in rows) else "legacy-compatible/v1"


def _read_verified_body(
    authority: _CorpusAuthority,
    row: Mapping[str, object],
    *,
    max_body_bytes: int,
    budget: _ReadBudget,
) -> _BodyRead:
    raw_sha = row.get("sha256")
    if not isinstance(raw_sha, str):
        return _BodyRead(CORRUPT)
    try:
        sha = _hex_sha(raw_sha, "row sha256")
    except ValueError:
        return _BodyRead(CORRUPT, sha256=raw_sha)
    try:
        raw = authority.read_bytes(
            ("objects", sha[:2], sha[2:]),
            max_bytes=max_body_bytes,
            budget=budget,
            missing_ok=True,
        )
    except _ReadFailure as exc:
        if exc.status == BODY_OVERSIZE:
            return _BodyRead(BODY_OVERSIZE, sha256=sha, bytes_read=exc.bytes_read, max_body_bytes=max_body_bytes)
        if exc.status == READ_BUDGET_EXHAUSTED:
            return _BodyRead(READ_BUDGET_EXHAUSTED, sha256=sha, bytes_read=exc.bytes_read, max_read_bytes=budget.limit)
        if exc.status == UNSAFE_PATH:
            return _BodyRead(UNSAFE_PATH, sha256=sha, bytes_read=exc.bytes_read)
        return _BodyRead(CORRUPT, sha256=sha, bytes_read=exc.bytes_read)
    except ValueError:
        return _BodyRead(UNSAFE_PATH, sha256=sha)
    if raw is None:
        return _BodyRead(MISSING, sha256=sha)
    checked = verify_stored_text(raw, sha, row.get("storage"))
    if checked.status != MATCH or checked.text is None:
        return _BodyRead(
            CORRUPT,
            text=None,
            sha256=checked.sha256 or sha,
            bytes_read=len(raw),
            source_sha256=checked.sha256 or sha,
            storage=checked.storage,
            storage_status=checked.storage_status or CORRUPT,
            storage_witnessed=checked.storage_witnessed,
        )
    view = _view_text(checked.text)
    view_sha = content_hash(view)
    return _BodyRead(
        MATCH,
        text=view,
        sha256=checked.sha256,
        bytes_read=len(raw),
        source_text=checked.text,
        source_sha256=checked.sha256,
        view_sha256=view_sha,
        storage=checked.storage,
        storage_status=checked.storage_status,
        storage_witnessed=checked.storage_witnessed,
    )


def _body_omission(body: _BodyRead | str) -> dict[str, object] | None:
    status = body.status if isinstance(body, _BodyRead) else body
    if status == MISSING:
        return {"reason": "body_missing"}
    if status == CORRUPT:
        return {"reason": "body_corrupt"}
    if status == UNSAFE_PATH:
        return {"reason": "unsafe_body_path"}
    if status == BODY_OVERSIZE:
        out: dict[str, object] = {"reason": "body_oversize"}
        if isinstance(body, _BodyRead) and body.max_body_bytes is not None:
            out["max_body_bytes"] = body.max_body_bytes
        return out
    if status == READ_BUDGET_EXHAUSTED:
        out = {"reason": "read_budget_exhausted"}
        if isinstance(body, _BodyRead) and body.max_read_bytes is not None:
            out["max_read_bytes"] = body.max_read_bytes
        return out
    if status != MATCH:
        return {"reason": "body_unverified", "status": status}
    return None


def _row_view(authority: _CorpusAuthority, row: dict, *, excerpt_chars: int, max_body_bytes: int, budget: _ReadBudget) -> dict[str, object]:
    ref = row_ref(row)
    omissions: list[dict[str, object]] = []
    body = _read_verified_body(authority, row, max_body_bytes=max_body_bytes, budget=budget)
    excerpt = ""
    end = 0
    text_chars = int(row.get("chars") or 0)
    if body.text is None:
        reason = _body_omission(body)
        if reason is not None:
            omissions.append(reason)
    else:
        text_chars = len(body.text)
        end = min(len(body.text), excerpt_chars)
        excerpt = body.text[:end]
        if end < len(body.text):
            omissions.append({"reason": "excerpt_truncated", "omitted_chars": len(body.text) - end})
    return {
        "row_ref": ref,
        "kind": str(row.get("kind", "")),
        "id": str(row.get("id", "")),
        "title": str(row.get("title", "")),
        "source": str(row.get("source", "")),
        "ref": str(row.get("ref", "")),
        "method": str(row.get("method", "")),
        "sha256": str(row.get("sha256", "")),
        "verified_sha256": body.sha256 if body.status == MATCH else "",
        "source_sha256": body.source_sha256 if body.status == MATCH else "",
        "view_sha256": body.view_sha256 if body.status == MATCH else "",
        "view_codec": VIEW_CODEC,
        "storage": body.storage,
        "storage_status": body.storage_status,
        "storage_witnessed": body.storage_witnessed,
        "derived_from": _list_field(row.get("derived_from")),
        "text_chars": text_chars,
        "source_text_chars": len(body.source_text) if body.source_text is not None else 0,
        "body_status": body.status,
        "body_bytes_read": body.bytes_read,
        "availability": assess_availability(row),
        "excerpt": excerpt,
        "excerpt_range": {"start": 0, "end": end},
        "omissions": omissions,
    }


def inspect_corpus(
    corpus: Corpus | str | os.PathLike[str],
    *,
    max_rows: object | None = None,
    excerpt_chars: object | None = None,
    max_catalog_bytes: object | None = None,
    max_catalog_rows: object | None = None,
    max_body_bytes: object | None = None,
    max_read_bytes: object | None = None,
) -> dict[str, object]:
    """Return bounded readable row previews from a stored corpus.

    The context surface hashes the exact body text it returns and refuses unsafe, missing,
    oversized, or tampered object reads instead of exporting unverified text.
    """
    c = _as_corpus(corpus)
    row_cap = _cap(max_rows, 20, "max_rows", hard=HARD_MAX_ROWS)
    excerpt_cap = _cap(excerpt_chars, DEFAULT_EXCERPT_CHARS, "excerpt_chars", hard=HARD_MAX_CHARS)
    catalog_bytes_cap = _cap(
        max_catalog_bytes,
        DEFAULT_MAX_CATALOG_BYTES,
        "max_catalog_bytes",
        hard=HARD_MAX_BYTES,
    )
    catalog_rows_cap = _cap(
        max_catalog_rows,
        DEFAULT_MAX_CATALOG_ROWS,
        "max_catalog_rows",
        hard=HARD_MAX_CATALOG_ROWS,
    )
    body_bytes_cap = _cap(max_body_bytes, DEFAULT_MAX_BODY_BYTES, "max_body_bytes", hard=HARD_MAX_BYTES)
    read_bytes_cap = _cap(max_read_bytes, DEFAULT_MAX_READ_BYTES, "max_read_bytes", hard=HARD_MAX_BYTES)
    with _CorpusAuthority(c) as authority:
        rows = _load_catalog_rows(authority, max_catalog_bytes=catalog_bytes_cap, max_catalog_rows=catalog_rows_cap)
        digest = digest_of_receipts(rows)
        returned = rows[:row_cap]
        budget = _ReadBudget(read_bytes_cap, read_bytes_cap)
        views = [
            _row_view(authority, row, excerpt_chars=excerpt_cap, max_body_bytes=body_bytes_cap, budget=budget)
            for row in returned
        ]
    omissions: list[dict[str, object]] = []
    if len(rows) > len(returned):
        omissions.append({"reason": "row_limit", "omitted_rows": len(rows) - len(returned)})
    return {
        "schema": INSPECT_SCHEMA,
        "corpus_digest": digest.seal,
        "corpus_digest_version": _corpus_digest_version(rows),
        "verified": len(returned) == len(rows) and all(row["body_status"] == MATCH for row in views),
        "verified_scope": "returned_rows" if len(returned) != len(rows) else "corpus",
        "row_count": len(rows),
        "returned_rows": len(views),
        "max_rows": row_cap,
        "excerpt_chars": excerpt_cap,
        "max_catalog_bytes": catalog_bytes_cap,
        "max_catalog_rows": catalog_rows_cap,
        "max_body_bytes": body_bytes_cap,
        "max_read_bytes": read_bytes_cap,
        "rows": views,
        "omissions": omissions,
        "does_not_prove": list(_DOES_NOT_PROVE),
    }


def parse_selection(value: object) -> dict[str, object]:
    if isinstance(value, str):
        parts = value.split(":")
        if not parts or not parts[0]:
            raise ValueError("selection needs a row_ref")
        out: dict[str, object] = {"row_ref": parts[0]}
        if len(parts) > 1 and parts[1] != "":
            try:
                out["start"] = int(parts[1])
            except ValueError as exc:
                raise ValueError("selection start must be an integer") from exc
        if len(parts) > 2 and parts[2] != "":
            try:
                out["limit"] = int(parts[2])
            except ValueError as exc:
                raise ValueError("selection limit must be an integer") from exc
        if len(parts) > 3:
            raise ValueError("selection format is ROW_REF[:START[:LIMIT]]")
        return out
    if isinstance(value, Mapping):
        extra = set(value) - {"row_ref", "start", "limit"}
        if extra:
            raise ValueError(f"selection has unexpected field(s): {', '.join(sorted(str(k) for k in extra))}")
        out = {"row_ref": value.get("row_ref")}
        if "start" in value:
            out["start"] = value["start"]
        if "limit" in value:
            out["limit"] = value["limit"]
        return out
    raise ValueError("selection must be a string or object")


def _selection_inputs(values: Sequence[object], *, max_count: int) -> list[dict[str, object]]:
    if isinstance(values, (str, bytes)):
        raise ValueError("select_context selections must be a sequence of selection objects")
    if len(values) > max_count:
        raise ValueError(f"select_context accepts at most {max_count} row(s)")
    return [parse_selection(value) for value in values]


def _int_field(value: object, name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"selection {name} must be an integer")
    if value < 0 if name == "start" else value < 1:
        raise ValueError(f"selection {name} is out of range")
    return value


def _select_one(
    authority: _CorpusAuthority,
    row: dict,
    spec: Mapping[str, object],
    *,
    default_limit: int,
    remaining_chars: int,
    max_body_bytes: int,
    budget: _ReadBudget,
) -> dict[str, object]:
    ref = row_ref(row)
    body = _read_verified_body(authority, row, max_body_bytes=max_body_bytes, budget=budget)
    if body.text is None:
        raise ValueError(f"cannot select row {ref}: body status {body.status}")
    start = _int_field(spec.get("start"), "start", 0)
    limit = _int_field(spec.get("limit"), "limit", default_limit)
    if start >= len(body.text):
        raise ValueError(f"cannot select row {ref}: start is past the body")
    requested_end = min(len(body.text), start + limit)
    requested_chars = requested_end - start
    if requested_chars > remaining_chars:
        raise ValueError("cannot select row: max_total_chars would be exceeded")
    selected = body.text[start:requested_end]
    return {
        "row_ref": ref,
        "kind": str(row.get("kind", "")),
        "id": str(row.get("id", "")),
        "title": str(row.get("title", "")),
        "source": str(row.get("source", "")),
        "ref": str(row.get("ref", "")),
        "method": str(row.get("method", "")),
        "sha256": str(row.get("sha256", "")),
        "verified_sha256": body.sha256,
        "source_sha256": body.source_sha256,
        "view_sha256": body.view_sha256,
        "view_codec": VIEW_CODEC,
        "storage": body.storage,
        "storage_status": body.storage_status,
        "storage_witnessed": body.storage_witnessed,
        "derived_from": _list_field(row.get("derived_from")),
        "full_text_chars": len(body.text),
        "full_source_chars": len(body.source_text) if body.source_text is not None else 0,
        "body_bytes_read": body.bytes_read,
        "range": {"start": start, "end": requested_end},
        "text": selected,
        "omissions": [],
    }


def select_context(
    corpus: Corpus | str | os.PathLike[str],
    selections: Sequence[object],
    *,
    expected_corpus_digest: str,
    max_rows: object | None = None,
    max_total_chars: object | None = None,
    default_limit: object | None = None,
    max_catalog_bytes: object | None = None,
    max_catalog_rows: object | None = None,
    max_body_bytes: object | None = None,
    max_read_bytes: object | None = None,
) -> dict[str, object]:
    """Build a portable private context payload from explicit corpus row/range selections."""
    c = _as_corpus(corpus)
    expected = _hex_sha(expected_corpus_digest, "expected_corpus_digest")
    row_cap = _cap(max_rows, DEFAULT_MAX_ROWS, "max_rows", hard=HARD_MAX_ROWS)
    total_cap = _cap(max_total_chars, DEFAULT_MAX_TOTAL_CHARS, "max_total_chars", hard=HARD_MAX_CHARS)
    default_cap = _cap(default_limit, DEFAULT_SELECTION_CHARS, "default_limit", hard=HARD_MAX_CHARS)
    catalog_bytes_cap = _cap(
        max_catalog_bytes,
        DEFAULT_MAX_CATALOG_BYTES,
        "max_catalog_bytes",
        hard=HARD_MAX_BYTES,
    )
    catalog_rows_cap = _cap(
        max_catalog_rows,
        DEFAULT_MAX_CATALOG_ROWS,
        "max_catalog_rows",
        hard=HARD_MAX_CATALOG_ROWS,
    )
    body_bytes_cap = _cap(max_body_bytes, DEFAULT_MAX_BODY_BYTES, "max_body_bytes", hard=HARD_MAX_BYTES)
    read_bytes_cap = _cap(max_read_bytes, DEFAULT_MAX_READ_BYTES, "max_read_bytes", hard=HARD_MAX_BYTES)
    specs = _selection_inputs(selections, max_count=row_cap)
    if not specs:
        raise ValueError("select_context requires at least one selection")
    with _CorpusAuthority(c) as authority:
        rows = _load_catalog_rows(authority, max_catalog_bytes=catalog_bytes_cap, max_catalog_rows=catalog_rows_cap)
        current = digest_of_receipts(rows).seal
        if current != expected:
            raise ValueError("expected corpus digest does not match current corpus digest")
        by_ref = {row_ref(row): row for row in rows}
        selected_rows: list[dict[str, object]] = []
        used_refs: set[str] = set()
        remaining = total_cap
        budget = _ReadBudget(read_bytes_cap, read_bytes_cap)
        for spec in specs:
            ref = spec.get("row_ref")
            if not isinstance(ref, str) or not ref.startswith("row_"):
                raise ValueError("selection needs a row_ref")
            if ref in used_refs:
                raise ValueError(f"duplicate selection row_ref: {ref}")
            used_refs.add(ref)
            if ref not in by_ref:
                raise ValueError(f"unknown row_ref: {ref}")
            selected = _select_one(
                authority,
                by_ref[ref],
                spec,
                default_limit=default_cap,
                remaining_chars=remaining,
                max_body_bytes=body_bytes_cap,
                budget=budget,
            )
            remaining -= len(str(selected["text"]))
            selected_rows.append(selected)
    base: dict[str, object] = {
        "schema": CONTEXT_SCHEMA,
        "corpus_digest": current,
        "corpus_digest_version": _corpus_digest_version(rows),
        "selection_count": len(selected_rows),
        "max_rows": row_cap,
        "max_total_chars": total_cap,
        "default_limit": default_cap,
        "max_catalog_bytes": catalog_bytes_cap,
        "max_catalog_rows": catalog_rows_cap,
        "max_body_bytes": body_bytes_cap,
        "max_read_bytes": read_bytes_cap,
        "total_text_chars": sum(len(str(row["text"])) for row in selected_rows),
        "selections": selected_rows,
        "omissions": [],
        "does_not_prove": list(_DOES_NOT_PROVE),
    }
    base["selection_digest"] = _sha(base)
    base["verified"] = True
    base["verified_scope"] = "selected_rows"
    return base
