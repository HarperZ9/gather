"""Sample rate, channels and duration of WAV, FLAC, Ogg and MP3 files, read from their headers.

Each reader takes an open binary file and the file size, and returns the fields it could read.
Ogg duration is left empty. MP3 duration is filled only from a Xing, Info or VBRI frame count. A
short or damaged header raises ``struct.error`` or ``ValueError``; ``gather.media_probe`` turns
that into empty fields and a note.
"""

from __future__ import annotations

import struct

_MAX_CHUNKS = 4096
_MP3_SCAN = 65536
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
_MP3_SAMPLES = {3: {3: 384, 2: 1152, 1: 1152}, 2: {3: 384, 2: 1152, 1: 576}, 0: {3: 384, 2: 1152, 1: 576}}


def wav(f, size: int) -> dict:
    """Walk the RIFF chunks for ``fmt `` and ``data``. Duration needs a ``data`` chunk that fits the file."""
    out: dict = {}
    pos, byte_rate = 12, 0
    for _ in range(_MAX_CHUNKS):
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            break
        kind, length = struct.unpack("<4sI", head)
        if kind == b"fmt ":
            _, channels, rate, byte_rate = struct.unpack("<HHII", f.read(12))
            out.update(sample_rate=rate, channels=channels)
        elif kind == b"data":
            if byte_rate and pos + 8 + length <= size:
                out["duration_seconds"] = round(length / byte_rate, 3)
            break
        pos += 8 + length + (length & 1)
    if "sample_rate" not in out:
        raise ValueError("WAV: no fmt chunk")
    return out


def flac(f, size: int) -> dict:
    f.seek(4)
    header, info = f.read(4), f.read(18)
    if len(header) < 4 or header[0] & 0x7F != 0:
        raise ValueError("FLAC: first block is not STREAMINFO")
    (packed,) = struct.unpack(">Q", info[10:18])
    rate, channels, samples = packed >> 44, ((packed >> 41) & 0x7) + 1, packed & 0xFFFFFFFFF
    if not rate:
        raise ValueError("FLAC: sample rate is zero")
    out = {"sample_rate": rate, "channels": channels}
    if samples:
        out["duration_seconds"] = round(samples / rate, 3)
    return out


def ogg(f, size: int) -> dict:
    """The Vorbis or Opus identification header on the first page. Opus gives its input sample rate."""
    f.seek(26)
    (segments,) = struct.unpack("B", f.read(1))
    f.seek(27 + segments)
    packet = f.read(32)
    if packet[:7] == b"\x01vorbis":
        channels, rate = struct.unpack("<BI", packet[11:16])
    elif packet[:8] == b"OpusHead":
        channels, _, rate = struct.unpack("<BHI", packet[9:16])
    else:
        raise ValueError("Ogg: first packet is neither Vorbis nor Opus")
    return {"sample_rate": rate, "channels": channels} if rate else {"channels": channels}


def id3_size(head: bytes) -> int:
    """The length of an ID3v2 tag at the start of the file, or 0 when there is none."""
    if len(head) < 10 or head[:3] != b"ID3":
        return 0
    body = (head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F)
    return 10 + body + (10 if head[5] & 0x10 else 0)


def mp3_header(word: bytes) -> tuple[int, int, int, int] | None:
    """(version bits, layer bits, sample rate, channels) for a valid frame header, else None."""
    if len(word) < 4 or word[0] != 0xFF or word[1] & 0xE0 != 0xE0:
        return None
    version, layer = (word[1] >> 3) & 3, (word[1] >> 1) & 3
    bitrate, rate_index = word[2] >> 4, (word[2] >> 2) & 3
    if version == 1 or layer == 0 or bitrate in (0, 15) or rate_index == 3:
        return None
    return version, layer, _MP3_RATES[version][rate_index], 1 if word[3] >> 6 == 3 else 2


def _mp3_frame_count(frame: bytes, version: int, channels: int) -> int:
    """Frames from a Xing or Info tag (when its frame-count flag is set) or a VBRI tag, else 0."""
    side = (17 if channels == 1 else 32) if version == 3 else (9 if channels == 1 else 17)
    tag = frame[4 + side:4 + side + 12]
    if tag[:4] in (b"Xing", b"Info") and len(tag) == 12 and tag[7] & 1:
        return int.from_bytes(tag[8:12], "big")
    vbri = frame[36:36 + 18]
    if vbri[:4] == b"VBRI" and len(vbri) == 18:
        return int.from_bytes(vbri[14:18], "big")
    return 0


def mp3(f, size: int) -> dict:
    f.seek(0)
    start = id3_size(f.read(10))
    f.seek(start)
    data = f.read(_MP3_SCAN)
    for i in range(max(0, len(data) - 3)):
        parsed = mp3_header(data[i:i + 4])
        if parsed is None:
            continue
        version, layer, rate, channels = parsed
        out: dict = {"sample_rate": rate, "channels": channels}
        frames = _mp3_frame_count(data[i:i + 64], version, channels) if layer == 1 else 0
        if frames:
            out["duration_seconds"] = round(frames * _MP3_SAMPLES[version][layer] / rate, 3)
        return out
    raise ValueError("MP3: no frame header found")
