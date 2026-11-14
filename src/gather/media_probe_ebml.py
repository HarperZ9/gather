"""WebM and Matroska (EBML): duration, picture size, sample rate and channels.

The reader parses the first 1 MiB of the file. When the Info or Tracks element is not there, it
follows the SeekHead to that element and reads up to 1 MiB at that offset. It stops at the first
Cluster, so media data is never read. A field that is not written in the file stays empty; the
format's default values are not filled in.
"""

from __future__ import annotations

import struct

from gather.media_probe_bmff import PartialRead

WINDOW = 1 << 20
_SEGMENT, _SEEK_HEAD, _SEEK, _SEEK_ID, _SEEK_POS = 0x18538067, 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
_INFO, _SCALE, _DURATION, _CLUSTER = 0x1549A966, 0x2AD7B1, 0x4489, 0x1F43B675
_TRACKS, _ENTRY, _VIDEO, _AUDIO = 0x1654AE6B, 0xAE, 0xE0, 0xE1
_WIDTH, _HEIGHT, _RATE, _CHANNELS = 0xB0, 0xBA, 0xB5, 0x9F


def vint(buf: bytes, pos: int, keep_marker: bool) -> tuple[int, int]:
    """(value, byte length) of the variable-length integer at ``pos``. An unknown size reads as -1."""
    if pos >= len(buf) or buf[pos] == 0:
        raise ValueError("EBML: bad variable-length integer")
    length = 9 - buf[pos].bit_length()
    data = buf[pos:pos + length]
    if len(data) < length:
        raise ValueError("EBML: integer cut short")
    value = int.from_bytes(data, "big")
    if keep_marker:
        return value, length
    mask = (1 << (7 * length)) - 1
    return (-1 if value & mask == mask else value & mask), length


def elements(buf: bytes, start: int, end: int):
    """Yield (id, data start, data end) for each element in a range; data end is clipped to the range."""
    pos = start
    while pos < end:
        ident, id_len = vint(buf, pos, True)
        size, size_len = vint(buf, pos + id_len, False)
        lo = pos + id_len + size_len
        hi = end if size < 0 else lo + size
        yield ident, lo, min(hi, end)
        pos = hi


def _uint(buf: bytes, lo: int, hi: int) -> int:
    return int.from_bytes(buf[lo:hi], "big")


def _float(buf: bytes, lo: int, hi: int) -> float:
    if hi - lo == 4:
        return struct.unpack(">f", buf[lo:hi])[0]
    return struct.unpack(">d", buf[lo:hi])[0]


def _info(buf: bytes, lo: int, hi: int, out: dict) -> None:
    scale, duration = 1000000, None
    for ident, a, b in elements(buf, lo, hi):
        if ident == _SCALE:
            scale = _uint(buf, a, b)
        elif ident == _DURATION:
            duration = _float(buf, a, b)
    if duration and duration > 0 and scale:
        out["duration_seconds"] = round(duration * scale / 1e9, 3)


def _tracks(buf: bytes, lo: int, hi: int, out: dict) -> None:
    for ident, a, b in elements(buf, lo, hi):
        if ident != _ENTRY:
            continue
        for kind, c, d in elements(buf, a, b):
            if kind == _VIDEO and "width" not in out:
                found = {i: _uint(buf, x, y) for i, x, y in elements(buf, c, d) if i in (_WIDTH, _HEIGHT)}
                if found.get(_WIDTH) and found.get(_HEIGHT):
                    out.update(width=found[_WIDTH], height=found[_HEIGHT])
            elif kind == _AUDIO and "sample_rate" not in out and "channels" not in out:
                for i, x, y in elements(buf, c, d):
                    if i == _RATE and _float(buf, x, y) > 0:
                        out["sample_rate"] = round(_float(buf, x, y))
                    elif i == _CHANNELS and _uint(buf, x, y):
                        out["channels"] = _uint(buf, x, y)


def _seeks(buf: bytes, lo: int, hi: int, base: int) -> dict[int, int]:
    """File offsets of the elements a SeekHead points at, keyed by element id."""
    found: dict[int, int] = {}
    for ident, a, b in elements(buf, lo, hi):
        if ident != _SEEK:
            continue
        parts = {i: _uint(buf, x, y) for i, x, y in elements(buf, a, b) if i in (_SEEK_ID, _SEEK_POS)}
        if _SEEK_ID in parts and _SEEK_POS in parts:
            found[parts[_SEEK_ID]] = base + parts[_SEEK_POS]
    return found


def _segment(f, buf: bytes, lo: int, hi: int, out: dict) -> None:
    readers = {_INFO: _info, _TRACKS: _tracks}
    seeks: dict[int, int] = {}
    seen: set[int] = set()
    for ident, a, b in elements(buf, lo, hi):
        if ident == _CLUSTER:
            break
        if ident == _SEEK_HEAD:
            seeks.update(_seeks(buf, a, b, lo))
        elif ident in readers:
            seen.add(ident)
            readers[ident](buf, a, b, out)
    for ident, reader in readers.items():
        if ident in seen or ident not in seeks:
            continue
        f.seek(seeks[ident])
        chunk = f.read(WINDOW)
        first = next(elements(chunk, 0, len(chunk)), None)
        if first and first[0] == ident:
            reader(chunk, first[1], first[2], out)


def ebml(f, size: int) -> dict:
    f.seek(0)
    buf = f.read(WINDOW)
    out: dict = {}
    try:
        for ident, lo, hi in elements(buf, 0, len(buf)):
            if ident == _SEGMENT:
                _segment(f, buf, lo, hi, out)
                break
    except (struct.error, ValueError) as exc:
        raise PartialRead(f"EBML: {exc}", out) from exc
    return out
