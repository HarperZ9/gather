"""Tempo, key, spectrum and decay estimates from PCM samples, in plain Python.

Every figure here is an estimate from programme material. The definitions follow the textbook
forms the engine's audio feature code uses: tempo is the strongest autocorrelation lag of an
onset envelope between 60 and 200 BPM, key is the best Krumhansl and Schmuckler profile match of
a chroma vector, the spectrum is an averaged windowed FFT, and the decay time is a line fit on a
Schroeder backward integration of the tail after the loudest moment. The decay figure is not a
room measurement: music keeps playing while it decays.

The work is bounded by fixed rules written into the tables: 5 ms energy frames, at most 16 FFT
windows of 4096 samples spread evenly over the analysed audio, and at most 8 key windows on a
copy decimated to about 11 kHz.
"""

from __future__ import annotations

import cmath
import math

FFT_SIZE, FFT_WINDOWS, KEY_WINDOWS, KEY_RATE = 4096, 16, 8, 11025
BANDS = tuple(31.25 * 2 ** k for k in range(10))
_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def frame_energy(x: list[float], rate: int) -> tuple[list[float], float]:
    """(mean square per 5 ms frame, frame length in seconds)."""
    hop = max(1, rate // 200)
    return [math.fsum(v * v for v in x[i:i + hop]) / hop for i in range(0, len(x) - hop + 1, hop)], hop / rate


def tempo(x: list[float], rate: int) -> float | None:
    """Beats per minute from the onset-envelope autocorrelation, or None under 4 s of audio."""
    energy, dt = frame_energy(x, rate)
    if len(energy) * dt < 4:
        return None
    level = [math.sqrt(e) for e in energy]
    onset = [max(0.0, b - a) for a, b in zip(level, level[1:], strict=False)]
    lo, hi = round(60 / (200 * dt)), round(60 / (60 * dt))
    scores = {lag: math.fsum(a * b for a, b in zip(onset, onset[lag:], strict=False)) / (len(onset) - lag)
              for lag in range(lo - 1, hi + 2)}
    best = max(range(lo, hi + 1), key=lambda lag: (scores[lag], -lag))
    if scores[best] <= 0:
        return None
    a, b, c = scores[best - 1], scores[best], scores[best + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c < 0 else 0.0
    return 60 / ((best + max(-0.5, min(0.5, shift))) * dt)


def _starts(length: int, size: int, count: int) -> list[int]:
    """Up to ``count`` window starts spread evenly over ``length`` samples."""
    if length <= size:
        return [0]
    count = min(count, length // size)
    return [round(i * (length - size) / max(1, count - 1)) for i in range(count)] if count > 1 else [0]


def _hann(size: int) -> list[float]:
    return [0.5 - 0.5 * math.cos(2 * math.pi * n / size) for n in range(size)]


def fft(values: list[complex]) -> list[complex]:
    """Radix-2 FFT of a power-of-two length list."""
    n = len(values)
    if n == 1:
        return values
    even, odd = fft(values[0::2]), fft(values[1::2])
    turn = [cmath.exp(-2j * cmath.pi * k / n) * odd[k] for k in range(n // 2)]
    return [even[k] + turn[k] for k in range(n // 2)] + [even[k] - turn[k] for k in range(n // 2)]


def spectrum(x: list[float], rate: int) -> dict:
    """Octave-band shares of energy (dB relative to the total) and the spectral centroid in Hz."""
    window = _hann(FFT_SIZE)
    power = [0.0] * (FFT_SIZE // 2)
    for start in _starts(len(x), FFT_SIZE, FFT_WINDOWS):
        chunk = x[start:start + FFT_SIZE]
        chunk = chunk + [0.0] * (FFT_SIZE - len(chunk))
        bins = fft([complex(v * w) for v, w in zip(chunk, window, strict=True)])
        for k in range(1, FFT_SIZE // 2):
            power[k] += bins[k].real ** 2 + bins[k].imag ** 2
    total = math.fsum(power)
    if total <= 0:
        return {"centroid_hz": None, "bands": [(centre, None) for centre in BANDS]}
    width = rate / FFT_SIZE
    bands = []
    for centre in BANDS:
        lo, hi = centre / math.sqrt(2), centre * math.sqrt(2)
        share = math.fsum(p for k, p in enumerate(power) if lo <= k * width < hi) / total
        bands.append((centre, 10 * math.log10(share) if share > 0 else None))
    return {"centroid_hz": math.fsum(k * width * p for k, p in enumerate(power)) / total, "bands": bands}


def chroma(x: list[float], rate: int) -> list[float] | None:
    """Energy per pitch class (C first) from a Goertzel bank over MIDI notes 36 to 83."""
    factor = max(1, rate // KEY_RATE)
    low = [math.fsum(x[i:i + factor]) / factor for i in range(0, len(x) - factor + 1, factor)]
    if len(low) < FFT_SIZE:
        return None
    window, out = _hann(FFT_SIZE), [0.0] * 12
    chunks = [[v * w for v, w in zip(low[s:s + FFT_SIZE], window, strict=True)] for s in _starts(len(low), FFT_SIZE, KEY_WINDOWS)]
    for note in range(36, 84):
        coeff = 2 * math.cos(2 * math.pi * 440 * 2 ** ((note - 69) / 12) / (rate / factor))
        for chunk in chunks:
            s1 = s2 = 0.0
            for v in chunk:
                s1, s2 = v + coeff * s1 - s2, s1
            out[note % 12] += s1 * s1 + s2 * s2 - coeff * s1 * s2
    return out if math.fsum(out) > 0 else None


def _pearson(a, b) -> float:
    ma, mb = math.fsum(a) / 12, math.fsum(b) / 12
    num = math.fsum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(math.fsum((x - ma) ** 2 for x in a) * math.fsum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def key(x: list[float], rate: int) -> tuple[str, float] | None:
    """(key name, profile correlation) for the best of the 24 major and minor keys, or None."""
    vector = chroma(x, rate)
    if vector is None:
        return None
    scores = []
    for tonic in range(12):
        turned = vector[tonic:] + vector[:tonic]
        scores.append((_pearson(turned, _MAJOR), f"{_NAMES[tonic]} major"))
        scores.append((_pearson(turned, _MINOR), f"{_NAMES[tonic]} minor"))
    best = max(scores, key=lambda s: (s[0], s[1]))
    return best[1], best[0]


def decay_time(x: list[float], rate: int) -> float | None:
    """Seconds for a 60 dB decay, from a -5 to -25 dB line fit on the tail after the loudest frame.

    None when the tail does not fall 25 dB, so steady sound gives no figure.
    """
    energy, dt = frame_energy(x, rate)
    if not energy or max(energy) <= 0:
        return None
    tail = energy[energy.index(max(energy)):]
    tenth = max(1, len(tail) // 10)
    if math.fsum(tail[-tenth:]) * 10 ** 2.5 > math.fsum(tail[:tenth]):
        return None  # the last tenth of the tail is not 25 dB under the first tenth: no decay to fit
    remaining, curve = math.fsum(tail), []
    for e in tail:
        curve.append(remaining)
        remaining -= e
    points = [(i * dt, 10 * math.log10(v / curve[0])) for i, v in enumerate(curve) if v > 0]
    fit = [(t, level) for t, level in points if -25 <= level <= -5]
    if len(fit) < 3 or not any(level < -25 for _, level in points):
        return None
    mt, ml = math.fsum(t for t, _ in fit) / len(fit), math.fsum(v for _, v in fit) / len(fit)
    slope = math.fsum((t - mt) * (v - ml) for t, v in fit) / math.fsum((t - mt) ** 2 for t, _ in fit)
    return -60 / slope if slope < 0 else None
