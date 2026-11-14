"""A palette table for PNG images, decoded with ``zlib`` and plain Python.

Handled: non-interlaced PNG at 8 bits per sample, colour types 0 (grey), 2 (RGB), 3 (palette)
and 6 (RGBA), up to ``MAX_PIXELS`` pixels. The palette rule is fixed: every pixel's red, green
and blue are cut to their top 4 bits (4096 bins), bins are counted, and the top ``TOP`` bins are
listed by count, then by colour, each shown as the colour at the centre of its bin. Alpha is not
used. Anything else raises ValueError with the reason.
"""

from __future__ import annotations

import struct
import zlib

MAX_PIXELS = 2_000_000
TOP = 8
PALETTE_RULE = "top 4 bits per channel (4096 bins), bin centre shown, alpha ignored"
_CHANNELS = {0: 1, 2: 3, 3: 1, 6: 4}
_MAX_CHUNKS = 100000


def _chunks(f):
    f.seek(8)
    for _ in range(_MAX_CHUNKS):
        head = f.read(8)
        if len(head) < 8:
            return
        length, kind = struct.unpack(">I4s", head)
        yield kind, length
        f.seek(length + 4, 1)


def _read(path: str) -> tuple[dict, bytes, bytes]:
    """(header fields, palette bytes, the inflated scanlines)."""
    header: dict = {}
    palette = b""
    inflater = zlib.decompressobj()
    limit = 0
    data = bytearray()
    with open(path, "rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG file")
        for kind, length in _chunks(f):
            at = f.tell()
            if kind == b"IHDR":
                width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", f.read(13))
                header = {"width": width, "height": height, "depth": depth, "colour": colour, "interlace": interlace}
                _check(header)
                limit = height * (1 + width * _CHANNELS[colour])
            elif kind == b"PLTE":
                palette = f.read(length)
            elif kind == b"IDAT" and header:
                data += inflater.decompress(f.read(length), limit + 1 - len(data))
                if len(data) > limit:
                    raise ValueError("more pixel data than the header declares")
            f.seek(at)
    if not header or len(data) != limit:
        raise ValueError("pixel data is missing or cut short")
    return header, palette, bytes(data)


def _check(header: dict) -> None:
    if header["depth"] != 8 or header["colour"] not in _CHANNELS or header["interlace"]:
        raise ValueError("only non-interlaced 8-bit grey, RGB, palette and RGBA PNG is decoded")
    if not 0 < header["width"] * header["height"] <= MAX_PIXELS:
        raise ValueError(f"image is empty or larger than the {MAX_PIXELS} pixel analysis bound")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unfilter(kind: int, line: bytearray, above: bytes, step: int) -> None:
    """Undo one scanline's PNG filter in place."""
    if kind == 1:
        for i in range(step, len(line)):
            line[i] = (line[i] + line[i - step]) & 255
    elif kind == 2:
        for i in range(len(line)):
            line[i] = (line[i] + above[i]) & 255
    elif kind == 3:
        for i in range(len(line)):
            line[i] = (line[i] + (((line[i - step] if i >= step else 0) + above[i]) >> 1)) & 255
    elif kind == 4:
        for i in range(len(line)):
            left, corner = (line[i - step], above[i - step]) if i >= step else (0, 0)
            line[i] = (line[i] + _paeth(left, above[i], corner)) & 255
    elif kind != 0:
        raise ValueError("unknown scanline filter")


def _bins(header: dict, palette: bytes, data: bytes) -> dict[tuple[int, int, int], int]:
    step = _CHANNELS[header["colour"]]
    stride = header["width"] * step
    above = bytes(stride)
    counts: dict[tuple[int, int, int], int] = {}
    for row in range(header["height"]):
        at = row * (stride + 1)
        line = bytearray(data[at + 1:at + 1 + stride])
        _unfilter(data[at], line, above, step)
        above = bytes(line)
        for i in range(0, stride, step):
            if header["colour"] == 0:
                rgb = (line[i], line[i], line[i])
            elif header["colour"] == 3:
                entry = palette[line[i] * 3:line[i] * 3 + 3]
                if len(entry) < 3:
                    raise ValueError("pixel names a colour outside the palette")
                rgb = (entry[0], entry[1], entry[2])
            else:
                rgb = (line[i], line[i + 1], line[i + 2])
            cut = (rgb[0] >> 4, rgb[1] >> 4, rgb[2] >> 4)
            counts[cut] = counts.get(cut, 0) + 1
    return counts


def png_palette(path: str) -> list[dict]:
    """Rows of rank, colour (``#rrggbb``), pixels and share for the most used colour bins."""
    try:
        header, palette, data = _read(path)
    except (zlib.error, struct.error) as exc:
        raise ValueError(f"PNG data could not be decoded: {type(exc).__name__}") from None
    counts = _bins(header, palette, data)
    total = header["width"] * header["height"]
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:TOP]
    return [{"rank": rank, "colour": "#" + "".join(f"{(c << 4) | 8:02x}" for c in cut), "pixels": count,
             "share": float(f"{count / total:.6g}")} for rank, (cut, count) in enumerate(top, 1)]
