"""Width and height of PNG, JPEG, GIF and WebP files, read from their headers.

Each reader takes an open binary file and returns the fields it could read. A short or damaged
header raises ``struct.error`` or ``ValueError``; ``gather.media_probe`` turns that into empty
fields and a note.
"""

from __future__ import annotations

import struct

_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_NO_LENGTH = frozenset(range(0xD0, 0xDA)) | {0x01}
_MAX_SEGMENTS = 4096


def png(f, size: int) -> dict:
    f.seek(8)
    length, kind, width, height = struct.unpack(">I4sII", f.read(16))
    if kind != b"IHDR" or length < 8:
        raise ValueError("PNG: first chunk is not IHDR")
    return {"width": width, "height": height}


def gif(f, size: int) -> dict:
    f.seek(6)
    width, height = struct.unpack("<HH", f.read(4))
    return {"width": width, "height": height}


def jpeg(f, size: int) -> dict:
    """Walk the marker segments to the first start-of-frame marker."""
    pos = 2
    for _ in range(_MAX_SEGMENTS):
        f.seek(pos)
        prefix, marker = struct.unpack("BB", f.read(2))
        if prefix != 0xFF:
            raise ValueError("JPEG: marker expected")
        if marker == 0xFF:
            pos += 1  # a fill byte before the marker
            continue
        if marker in _NO_LENGTH:
            pos += 2
            continue
        (length,) = struct.unpack(">H", f.read(2))
        if marker in _SOF:
            _, height, width = struct.unpack(">BHH", f.read(5))
            return {"width": width, "height": height}
        if marker == 0xDA or length < 2:
            break
        pos += 2 + length
    raise ValueError("JPEG: no start-of-frame marker")


def webp(f, size: int) -> dict:
    f.seek(12)
    kind = f.read(4)
    f.seek(20)
    if kind == b"VP8X":
        data = f.read(10)
        struct.unpack("10B", data)
        return {"width": int.from_bytes(data[4:7], "little") + 1, "height": int.from_bytes(data[7:10], "little") + 1}
    if kind == b"VP8L":
        signature, bits = struct.unpack("<BI", f.read(5))
        if signature != 0x2F:
            raise ValueError("WebP: bad lossless signature")
        return {"width": (bits & 0x3FFF) + 1, "height": ((bits >> 14) & 0x3FFF) + 1}
    if kind == b"VP8 ":
        tag, start, width, height = struct.unpack("<3s3sHH", f.read(10))
        if start != b"\x9d\x01\x2a":
            raise ValueError("WebP: bad lossy start code")
        return {"width": width & 0x3FFF, "height": height & 0x3FFF}
    raise ValueError("WebP: unknown first chunk")
