"""ISO base media files (MP4, MOV, M4A): duration, picture size, sample rate and channels.

The reader walks box headers and seeks past payloads, so a ``moov`` box after a large ``mdat`` is
found without reading the media data. It handles 64-bit box sizes and a box that runs to the end
of the file. Only small boxes (``mvhd``, ``tkhd``, ``hdlr``, ``mdhd``, ``stsd``) are read.
"""

from __future__ import annotations

import struct

_MAX_BOXES = 20000
_MAX_PAYLOAD = 1 << 20


class PartialRead(ValueError):
    """A reader stopped early; ``fields`` holds what it read before the damage."""

    def __init__(self, message: str, fields: dict):
        super().__init__(message)
        self.fields = fields


_BRANDS = {b"qt  ": "mov", b"M4A ": "m4a", b"M4B ": "m4a", b"M4P ": "m4a"}


def brand(head: bytes) -> str:
    """The container name for a file whose first box is ``ftyp``."""
    return _BRANDS.get(head[8:12], "mp4")


def boxes(f, start: int, end: int):
    """Yield (type, payload start, payload end) for each box between two offsets."""
    pos = start
    for _ in range(_MAX_BOXES):
        if pos + 8 > end:
            return
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            (size,) = struct.unpack(">Q", f.read(8))
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise ValueError("BMFF: box size runs past its parent")
        yield kind, pos + header, pos + size
        pos += size


def _find(f, start: int, end: int, *path: bytes) -> tuple[int, int] | None:
    """The payload range of the first box at a nested path, or None."""
    for kind, lo, hi in boxes(f, start, end):
        if kind == path[0]:
            return (lo, hi) if len(path) == 1 else _find(f, lo, hi, *path[1:])
    return None


def _payload(f, span: tuple[int, int] | None, limit: int = _MAX_PAYLOAD) -> bytes:
    if span is None:
        return b""
    f.seek(span[0])
    return f.read(min(span[1] - span[0], limit))


def _timed(data: bytes) -> tuple[int, int]:
    """(timescale, duration) from an ``mvhd`` or ``mdhd`` payload, version 0 or 1."""
    if data[:1] == b"\x01":
        timescale, duration = struct.unpack(">IQ", data[20:32])
        return timescale, 0 if duration == 0xFFFFFFFFFFFFFFFF else duration
    timescale, duration = struct.unpack(">II", data[12:20])
    return timescale, 0 if duration == 0xFFFFFFFF else duration


def _track(f, lo: int, hi: int) -> dict:
    """What one ``trak`` box says: picture size from ``tkhd``, audio fields from ``mdia``."""
    out: dict = {}
    tkhd = _payload(f, _find(f, lo, hi, b"tkhd"))
    if len(tkhd) >= 8:
        width, height = struct.unpack(">II", tkhd[-8:])
        if width >> 16 and height >> 16:
            out.update(width=width >> 16, height=height >> 16)
    mdia = _find(f, lo, hi, b"mdia")
    if mdia is None:
        return out
    handler = _payload(f, _find(f, *mdia, b"hdlr"), 12)[8:12]
    if handler != b"soun":
        return out
    stsd = _payload(f, _find(f, *mdia, b"minf", b"stbl", b"stsd"), 64)
    channels, rate = struct.unpack(">H", stsd[32:34])[0], struct.unpack(">I", stsd[40:44])[0] >> 16
    if not rate:
        rate = _timed(_payload(f, _find(f, *mdia, b"mdhd"), 32))[0]
    out.update(sample_rate=rate, channels=channels)
    return out


def bmff(f, size: int) -> dict:
    moov = _find(f, 0, size, b"moov")
    if moov is None:
        raise ValueError("BMFF: no moov box")
    out: dict = {}
    try:
        for kind, lo, hi in boxes(f, *moov):
            if kind == b"mvhd":
                f.seek(lo)
                timescale, duration = _timed(f.read(min(hi - lo, 32)))
                if timescale and duration:
                    out["duration_seconds"] = round(duration / timescale, 3)
            elif kind == b"trak":
                for key, value in _track(f, lo, hi).items():
                    if value:
                        out.setdefault(key, value)
    except (struct.error, ValueError) as exc:
        raise PartialRead(f"BMFF: {exc}", out) from exc
    return out
