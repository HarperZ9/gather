"""Read uncompressed PCM from a WAV file and measure its level and loudness, standard library only.

Only the first ``ANALYSIS_SECONDS`` seconds are read, a fixed rule that bounds the run time and
is written beside every figure. Supported: integer PCM at 8, 16, 24 or 32 bits, one or two
channels, any sample rate. Integrated loudness follows ITU-R BS.1770: K-weighting (the two
filters derived for the file's own sample rate), 400 ms blocks with 75 percent overlap, the
absolute gate at -70 LUFS and the relative gate 10 LU under the ungated mean.

Results are rounded to 6 significant digits by ``sig``. The arithmetic is IEEE double precision
with ``math`` functions, which can differ in the last bits between platforms; the rounding is
there to absorb that, and it is not a proof that it always will.
"""

from __future__ import annotations

import array
import math
import struct
import sys
from dataclasses import dataclass

ANALYSIS_SECONDS = 30
WINDOW_RULE = f"first {ANALYSIS_SECONDS} s of the file"
_MAX_CHUNKS = 4096


@dataclass
class Pcm:
    rate: int
    bits: int
    channels: list[list[float]]
    frames_total: int

    @property
    def frames(self) -> int:
        return len(self.channels[0]) if self.channels else 0

    def mono(self) -> list[float]:
        if len(self.channels) == 1:
            return self.channels[0]
        return [(a + b) / 2 for a, b in zip(self.channels[0], self.channels[1], strict=True)]


def sig(value: float, digits: int = 6) -> float:
    """``value`` rounded to 6 significant digits (under 1e-12 reads as 0), the one rounding rule for every table."""
    return 0.0 if abs(value) < 1e-12 else float(f"{value:.{digits}g}")


def db(ratio: float) -> float | None:
    return 20 * math.log10(ratio) if ratio > 0 else None


def _layout(f) -> tuple[dict, int, int]:
    """(fmt fields, data offset, data length) from the RIFF chunks."""
    fmt: dict = {}
    pos = 12
    for _ in range(_MAX_CHUNKS):
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            break
        ident, length = struct.unpack("<4sI", head)
        if ident == b"fmt ":
            body = f.read(min(length, 40))
            tag, channels, rate, _, align, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = {"tag": tag, "channels": channels, "rate": rate, "align": align, "bits": bits}
        elif ident == b"data":
            return fmt, pos + 8, length
        pos += 8 + length + (length & 1)
    raise ValueError("no data chunk")


def _samples(raw: bytes, bits: int) -> list[float]:
    scale = float(1 << (bits - 1))
    if bits == 8:
        return [(b - 128) / scale for b in raw]
    if bits == 24:
        return [int.from_bytes(raw[i:i + 3], "little", signed=True) / scale for i in range(0, len(raw) - 2, 3)]
    values = array.array("h" if bits == 16 else "i")
    values.frombytes(raw[:len(raw) - len(raw) % values.itemsize])
    if sys.byteorder == "big":
        values.byteswap()
    return [v / scale for v in values]


def read_pcm(path: str) -> Pcm:
    """The first ``ANALYSIS_SECONDS`` of a PCM WAV as floats in -1..1. Raises ValueError with the reason."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError("not a RIFF WAVE file")
        fmt, start, length = _layout(f)
        if not fmt:
            raise ValueError("no fmt chunk before the data")
        if fmt["tag"] != 1 or fmt["bits"] not in (8, 16, 24, 32) or fmt["channels"] not in (1, 2) or not fmt["rate"]:
            raise ValueError("not 8, 16, 24 or 32-bit integer PCM in one or two channels")
        width = fmt["bits"] // 8 * fmt["channels"]
        if array.array("i").itemsize != 4 or fmt["align"] != width:
            raise ValueError("sample layout not handled")
        frames = min(length // width, fmt["rate"] * ANALYSIS_SECONDS)
        f.seek(start)
        flat = _samples(f.read(frames * width), fmt["bits"])
    count = fmt["channels"]
    channels = [flat[c::count] for c in range(count)]
    if not channels[0]:
        raise ValueError("the data chunk holds no whole sample frame")
    return Pcm(rate=fmt["rate"], bits=fmt["bits"], channels=channels, frames_total=length // width)


def levels(pcm: Pcm) -> dict:
    """Sample peak, RMS, crest factor and DC offset over every channel."""
    count = sum(len(ch) for ch in pcm.channels)
    peak = max(max(abs(min(ch)), abs(max(ch))) for ch in pcm.channels)
    rms = math.sqrt(sum(math.fsum(v * v for v in ch) for ch in pcm.channels) / count)
    peak_db, rms_db = db(peak), db(rms)
    crest = peak_db - rms_db if peak_db is not None and rms_db is not None else None
    return {"sample_peak_dbfs": peak_db, "rms_dbfs": rms_db, "crest_factor_db": crest,
            "dc_offset": math.fsum(math.fsum(ch) for ch in pcm.channels) / count}


def k_weighting(rate: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The BS.1770 shelving and high-pass biquads for a sample rate, as (b0, b1, b2, a1, a2) each."""
    k = math.tan(math.pi * 1681.974450955533 / rate)
    q, vh = 0.7071752369554196, 10 ** (3.999843853973347 / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = ((vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    k = math.tan(math.pi * 38.13547087602444 / rate)
    q = 0.5003270373238773
    a0 = 1 + k / q + k * k
    return shelf, (1.0, -2.0, 1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)


def _biquad(x: list[float], coeff: tuple[float, ...]) -> list[float]:
    b0, b1, b2, a1, a2 = coeff
    out = []
    x1 = x2 = y1 = y2 = 0.0
    for v in x:
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, y
        out.append(y)
    return out


def integrated_loudness(pcm: Pcm) -> float | None:
    """Integrated loudness in LUFS (BS.1770, gated), or None when no block passes the gates."""
    step = pcm.rate // 10
    blocks = (pcm.frames - 4 * step) // step + 1 if step and pcm.frames >= 4 * step else 0
    if blocks < 1:
        return None
    shelf, high_pass = k_weighting(pcm.rate)
    power = [0.0] * blocks
    for channel in pcm.channels:
        weighted = _biquad(_biquad(channel, shelf), high_pass)
        steps = [math.fsum(v * v for v in weighted[i * step:(i + 1) * step]) for i in range(blocks + 3)]
        for j in range(blocks):
            power[j] += (steps[j] + steps[j + 1] + steps[j + 2] + steps[j + 3]) / (4 * step)
    loud = [p for p in power if p > 0 and -0.691 + 10 * math.log10(p) > -70]
    if not loud:
        return None
    gate = -0.691 + 10 * math.log10(math.fsum(loud) / len(loud)) - 10
    kept = [p for p in loud if -0.691 + 10 * math.log10(p) > gate]
    return -0.691 + 10 * math.log10(math.fsum(kept) / len(kept)) if kept else None
