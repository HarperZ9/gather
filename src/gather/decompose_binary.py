"""Structural handlers for PNG and WAV, and the raw fallback.

Each ``build_*`` takes a ``Maker`` and returns the root node for the whole source. A handler
raises ``ValueError`` or ``struct.error`` when the bytes are not what it expects, and the front
door then tries the next handler. Bytes after the last understood chunk stay in the tree as
``raw`` nodes.
"""

from __future__ import annotations

import struct
import zlib

from gather.decompose_tree import Maker

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_CHUNKS = 200000


def build_raw(m: Maker, ctx, depth: int) -> dict:
    """The whole source as one byte range."""
    return m.leaf("raw", 0, m.src.size)


def _crc(m: Maker, start: int, length: int) -> int:
    value = 0
    for data in m.src.chunks(start, length):
        value = zlib.crc32(data, value)
    return value


def _ihdr(data: bytes) -> dict:
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", data[:13])
    return {"width": width, "height": height, "bit_depth": depth, "colour_type": colour, "interlace": interlace}


def _png_chunk(m: Maker, pos: int) -> dict | None:
    """One chunk at ``pos`` as length, type, data and CRC fields, or None when it does not fit."""
    head = m.src.read(pos, 8)
    if len(head) < 8:
        return None
    length, kind = struct.unpack(">I4s", head)
    if pos + 12 + length > m.src.size:
        return None
    stored = struct.unpack(">I", m.src.read(pos + 8 + length, 4))[0]
    name = kind.decode("latin-1")
    fields = [m.leaf("length", pos, 4, value=length), m.leaf("type", pos + 4, 4, value=name)]
    if length:
        fields.append(m.leaf("data", pos + 8, length))
    ok = _crc(m, pos + 4, 4 + length) == stored
    fields.append(m.leaf("crc", pos + 8 + length, 4, value=f"{stored:08x}", matches=ok))
    params = {"type": name, "crc_ok": ok}
    if kind == b"IHDR" and length >= 13:
        params.update(_ihdr(m.src.read(pos + 8, 13)))
    return m.group("png-chunk", fields, **params)


def build_png(m: Maker, ctx, depth: int) -> dict:
    if m.src.read(0, 8) != PNG_SIGNATURE:
        raise ValueError("not a PNG signature")
    parts = [m.leaf("png-signature", 0, 8)]
    pos = 8
    for _ in range(_MAX_CHUNKS):
        chunk = _png_chunk(m, pos)
        if chunk is None:
            break
        parts.append(chunk)
        pos += chunk["length"]
    return m.cover("png", 0, m.src.size, parts, chunks=len(parts) - 1)


def _fmt(data: bytes) -> dict:
    tag, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", data[:16])
    return {"format_tag": tag, "channels": channels, "sample_rate": rate, "byte_rate": byte_rate,
            "block_align": align, "bits_per_sample": bits}


def _wav_data(m: Maker, start: int, length: int, fmt: dict) -> list[dict]:
    """The data chunk's payload as sample frames, plus any bytes short of a whole frame."""
    align = fmt.get("block_align", 0)
    if not align or not length:
        return [m.leaf("data", start, length)] if length else []
    whole = length - length % align
    parts = [m.leaf("pcm-frames", start, whole, unit="sample frame", unit_size=align, unit_count=whole // align,
                    channels=fmt["channels"], bits_per_sample=fmt["bits_per_sample"])] if whole else []
    if length - whole:
        parts.append(m.leaf("raw", start + whole, length - whole))
    return parts


def _wav_chunk(m: Maker, pos: int, fmt: dict) -> dict | None:
    head = m.src.read(pos, 8)
    if len(head) < 8:
        return None
    ident, length = struct.unpack("<4sI", head)
    if pos + 8 + length > m.src.size:
        return None
    name = ident.decode("latin-1")
    fields = [m.leaf("id", pos, 4, value=name), m.leaf("size", pos + 4, 4, value=length)]
    params: dict = {"id": name}
    if ident == b"fmt " and length >= 16:
        fmt.update(_fmt(m.src.read(pos + 8, 16)))
        params.update(fmt)
    if ident == b"data":
        fields += _wav_data(m, pos + 8, length, fmt)
    elif length:
        fields.append(m.leaf("data", pos + 8, length))
    if length & 1 and pos + 8 + length < m.src.size:
        fields.append(m.leaf("pad", pos + 8 + length, 1))
    return m.group("riff-chunk", fields, **params)


def build_wav(m: Maker, ctx, depth: int) -> dict:
    head = m.src.read(0, 12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise ValueError("not a RIFF WAVE header")
    parts = [m.leaf("riff-id", 0, 4, value="RIFF"), m.leaf("riff-size", 4, 4, value=struct.unpack("<I", head[4:8])[0]),
             m.leaf("form", 8, 4, value="WAVE")]
    fmt: dict = {}
    pos = 12
    for _ in range(_MAX_CHUNKS):
        chunk = _wav_chunk(m, pos, fmt)
        if chunk is None:
            break
        parts.append(chunk)
        pos += chunk["length"]
    return m.cover("wav", 0, m.src.size, parts, **fmt)
