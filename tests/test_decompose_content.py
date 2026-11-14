"""The content level of ``gather decompose``: each measurement against a synthetic input with a
known answer and a stated tolerance, the status rows for what cannot run, and byte-identical
tables on a second run."""

import csv
import hashlib
import json
import math
import struct
import zlib

import pytest
from test_decompose import png_chunk

from gather.cli import main
from gather.decompose_content import COLUMNS, NO_DECODER, NO_TOOL
from gather.decompose_dsp import decay_time, key, spectrum, tempo
from gather.decompose_pcm import integrated_loudness, levels, read_pcm
from gather.decompose_run import decompose_file


def sine(freq, rate, seconds, amplitude=1.0):
    return [amplitude * math.sin(2 * math.pi * freq * n / rate) for n in range(int(rate * seconds))]


def lcg_noise(count, seed=12345):
    """Uniform noise in -1..1 from a fixed-seed linear congruential generator."""
    out, state = [], seed
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state / (1 << 30) - 1)
    return out


def clicks(bpm, rate=22050, seconds=12):
    x = [0.0] * (rate * seconds)
    beat = 0
    while beat * 60 / bpm < seconds:
        start = int(beat * 60 / bpm * rate)
        for i in range(min(200, len(x) - start)):
            x[start + i] = math.sin(2 * math.pi * 1000 * i / rate) * (1 - i / 200)
        beat += 1
    return x


def chord(notes, rate=22050, seconds=3):
    return [sum(math.sin(2 * math.pi * 440 * 2 ** ((m - 69) / 12) * n / rate) for m in notes) / len(notes)
            for n in range(rate * seconds)]


def wav_file(path, channels, rate, bits=16, tag=1):
    top = (1 << (bits - 1)) - 1
    frames = bytearray()
    for frame in zip(*channels, strict=True):
        for v in frame:
            value = round(v * top)
            frames += bytes([value + 128]) if bits == 8 else value.to_bytes(bits // 8, "little", signed=True)
    align = bits // 8 * len(channels)
    fmt = struct.pack("<HHIIHH", tag, len(channels), rate, rate * align, align, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(frames)) + bytes(frames)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def table(out, name):
    with open(out / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def measures(out):
    return {r["measure"]: r["value"] for r in table(out, "audio_measurements.csv")}


def test_integrated_loudness_of_a_full_scale_997_hz_sine_is_minus_3_01_lufs(tmp_path):
    tone = sine(997, 48000, 3)
    mono = read_pcm(wav_file(tmp_path / "mono.wav", [tone], 48000))
    assert integrated_loudness(mono) == pytest.approx(-3.01, abs=0.05)  # BS.1770: one channel at 0 dBFS reads -3.01
    stereo = read_pcm(wav_file(tmp_path / "stereo.wav", [tone, tone], 48000))
    assert integrated_loudness(stereo) == pytest.approx(0.0, abs=0.05)
    quiet = read_pcm(wav_file(tmp_path / "quiet.wav", [sine(997, 48000, 3, 0.1)], 48000))
    assert integrated_loudness(quiet) == pytest.approx(-23.01, abs=0.05)
    assert integrated_loudness(read_pcm(wav_file(tmp_path / "short.wav", [tone[:9000]], 48000))) is None  # under 400 ms


def test_peak_rms_crest_and_dc_offset_match_a_sine_with_a_known_offset(tmp_path):
    shifted = [0.5 * v + 0.25 for v in sine(440, 8000, 2)]
    for bits, tolerance in ((8, 0.2), (16, 0.01), (24, 0.01), (32, 0.01)):
        got = levels(read_pcm(wav_file(tmp_path / f"s{bits}.wav", [shifted], 8000, bits)))
        assert got["sample_peak_dbfs"] == pytest.approx(20 * math.log10(0.75), abs=tolerance), bits
        assert got["rms_dbfs"] == pytest.approx(10 * math.log10(0.25 ** 2 + 0.5 ** 2 / 2), abs=tolerance), bits
        assert got["crest_factor_db"] == pytest.approx(got["sample_peak_dbfs"] - got["rms_dbfs"], abs=1e-9)
        assert got["dc_offset"] == pytest.approx(0.25, abs=0.005), bits
    with pytest.raises(ValueError, match="integer PCM"):
        read_pcm(wav_file(tmp_path / "float.wav", [shifted], 8000, 32, tag=3))


def test_tempo_of_a_click_track_is_within_one_and_a_half_bpm():
    for bpm in (75, 90, 120, 140):
        assert tempo(clicks(bpm), 22050) == pytest.approx(bpm, abs=1.5), bpm
    assert tempo(clicks(120, seconds=3), 22050) is None  # under 4 s of audio
    assert tempo([0.0] * 22050 * 5, 22050) is None  # no onsets


def test_key_of_a_triad_or_a_scale_is_named():
    assert key(chord([60, 64, 67]), 22050)[0] == "C major"
    assert key(chord([57, 60, 64]), 22050)[0] == "A minor"
    assert key(chord([62, 66, 69], rate=44100), 44100)[0] == "D major"
    name, correlation = key(chord([60, 62, 64, 65, 67, 69, 71, 72]), 22050)
    assert name == "C major" and 0.8 < correlation <= 1.0
    assert key([0.0] * 22050, 22050) is None and key(chord([60], seconds=1)[:2000], 22050) is None


def test_spectrum_puts_a_1_khz_tone_in_the_1_khz_band():
    got = spectrum(sine(1000, 48000, 2), 48000)
    assert got["centroid_hz"] == pytest.approx(1000, abs=5)
    bands = dict(got["bands"])
    assert bands[1000.0] == pytest.approx(0.0, abs=0.01)
    assert all(value < -60 for centre, value in bands.items() if centre != 1000.0)
    assert spectrum([0.0] * 5000, 48000)["centroid_hz"] is None


def test_decay_estimate_of_a_noise_burst_with_a_half_second_decay_is_within_ten_percent():
    rate, target = 24000, 0.5
    burst = [v * 10 ** (-3 * (n / rate) / target) for n, v in enumerate(lcg_noise(rate * 2))]
    assert decay_time(burst, rate) == pytest.approx(target, rel=0.10)
    assert decay_time(lcg_noise(rate), rate) is None  # steady noise never falls 25 dB


def test_wav_content_tables_and_component_rows(tmp_path):
    path = wav_file(tmp_path / "clicks.wav", [clicks(120, rate=16000, seconds=6)], 16000)
    doc = decompose_file(path, str(tmp_path / "out"))
    got = measures(tmp_path / "out")
    assert float(got["tempo_estimate"]) == pytest.approx(120, abs=1.5)
    assert (got["frames_analysed"], got["frames_total"]) == ("96000", "96000")
    assert set(got) >= {"sample_peak", "rms_level", "crest_factor", "dc_offset", "integrated_loudness", "key_estimate",
                        "spectral_centroid", "decay_time_60db_estimate"}
    assert {r["window"] for r in table(tmp_path / "out", "audio_measurements.csv")} == {"first 30 s of the file"}
    assert len(table(tmp_path / "out", "audio_spectrum.csv")) == 10
    rows = table(tmp_path / "out", "components.csv")
    assert tuple(rows[0]) == COLUMNS
    status = {r["component"]: r["status"] for r in rows}
    assert status["container facts"] == status["tempo estimate"] == status["integrated loudness"] == "ok"
    assert status["stems"] == status["transcript with timestamps"] == NO_TOOL
    for row in rows:
        if row["path"]:
            assert row["sha256"] == hashlib.sha256((tmp_path / "out" / row["path"]).read_bytes()).hexdigest()
    with open(tmp_path / "out" / "components.jsonl", encoding="utf-8") as f:
        assert [json.loads(line) for line in f] == doc["content"]
    assert {r["deterministic"] for r in rows if r["component"] == "stems"} == {
        "no (model output; repeatable only with pinned weights, a fixed seed and one device)"}


def test_compressed_media_gets_container_facts_and_not_run_rows(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"\xff\xfb\x90\x64" + b"\0" * 400)
    decompose_file(str(tmp_path / "a.mp3"), str(tmp_path / "out"))
    rows = {r["component"]: r for r in table(tmp_path / "out", "components.csv")}
    assert (rows["container facts"]["status"], rows["container facts"]["kind"]) == ("ok", "audio")
    assert {"field": "sample_rate", "value": "44100"} in table(tmp_path / "out", "container.csv")
    for name in ("integrated loudness", "tempo estimate", "key estimate", "spectrum summary", "decay time estimate"):
        assert (rows[name]["status"], rows[name]["path"], rows[name]["sha256"]) == (NO_DECODER, "", "")
    wav_file(tmp_path / "float.wav", [sine(440, 8000, 1)], 8000, 32, tag=3)
    decompose_file(str(tmp_path / "float.wav"), str(tmp_path / "out2"))
    float_rows = {r["component"]: r["status"] for r in table(tmp_path / "out2", "components.csv")}
    assert float_rows["RMS level"] == "not run (not 8, 16, 24 or 32-bit integer PCM in one or two channels)"


def rgb_png(rows, filters, colour=2, palette=None, interlace=0):
    width = len(rows[0]) // (3 if colour == 2 else 1)
    lines, above = b"", bytes(len(rows[0]))
    for row, kind in zip(rows, filters, strict=True):
        coded = bytes((v - above[i]) & 255 for i, v in enumerate(row)) if kind == 2 else bytes(row)
        lines += bytes([kind]) + coded
        above = bytes(row)
    plte = png_chunk(b"PLTE", palette) if palette else b""
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 8, colour, 0, 0, interlace))
            + plte + png_chunk(b"IDAT", zlib.compress(lines)) + png_chunk(b"IEND", b""))


def test_png_palette_counts_colour_bins_through_scanline_filters(tmp_path):
    red, blue, near_red = [250, 10, 10], [0, 0, 255], [245, 5, 12]
    rows = [red + red + blue + near_red, red + blue + blue + red]
    (tmp_path / "a.png").write_bytes(rgb_png(rows, filters=[0, 2]))
    decompose_file(str(tmp_path / "a.png"), str(tmp_path / "out"))
    assert table(tmp_path / "out", "image_palette.csv") == [
        {"rank": "1", "colour": "#f80808", "pixels": "5", "share": "0.625"},
        {"rank": "2", "colour": "#0808f8", "pixels": "3", "share": "0.375"}]
    indexed = rgb_png([[0, 1, 1, 1]], [0], colour=3, palette=bytes([255, 255, 255, 0, 128, 0]))
    (tmp_path / "b.png").write_bytes(indexed)
    decompose_file(str(tmp_path / "b.png"), str(tmp_path / "out2"))
    assert [(r["colour"], r["pixels"]) for r in table(tmp_path / "out2", "image_palette.csv")] == [("#088808", "3"), ("#f8f8f8", "1")]
    (tmp_path / "c.png").write_bytes(rgb_png(rows, [0, 0], interlace=1))
    decompose_file(str(tmp_path / "c.png"), str(tmp_path / "out3"))
    palette = next(r for r in table(tmp_path / "out3", "components.csv") if r["component"] == "palette")
    assert palette["status"] == "not run (only non-interlaced 8-bit grey, RGB, palette and RGBA PNG is decoded)"
    assert next(r for r in table(tmp_path / "out3", "components.csv") if r["component"] == "embedded text")["status"] == NO_TOOL


def test_document_tables_list_headings_and_references(tmp_path):
    (tmp_path / "notes.md").write_text("# Title\n\nSee https://doi.org/10.5555/abc on 2026-11-14.\n\n## Part two ##\n", encoding="utf-8")
    decompose_file(str(tmp_path / "notes.md"), str(tmp_path / "out"))
    assert table(tmp_path / "out", "document_headings.csv") == [
        {"order": "1", "level": "1", "text": "Title"}, {"order": "2", "level": "2", "text": "Part two"}]
    assert {(r["type"], r["normalized"]) for r in table(tmp_path / "out", "document_references.csv")} == {
        ("url", "https://doi.org/10.5555/abc"), ("doi", "10.5555/abc"), ("date", "2026-11-14")}
    assert {"field": "form", "value": "text"} in table(tmp_path / "out", "document_facts.csv")
    html = "<!DOCTYPE html><html><head><style>h1{color:red}</style></head><body><h1>Top <b>line</b></h1><p>Body 45%</p></body></html>"
    (tmp_path / "page.bin").write_text(html, encoding="utf-8")
    decompose_file(str(tmp_path / "page.bin"), str(tmp_path / "out2"))
    assert table(tmp_path / "out2", "document_headings.csv") == [{"order": "1", "level": "1", "text": "Top line"}]
    facts = {r["field"]: r["value"] for r in table(tmp_path / "out2", "document_facts.csv")}
    assert (facts["form"], facts["text_length"]) == ("html", str(len("Top lineBody 45%")))
    assert [r["normalized"] for r in table(tmp_path / "out2", "document_references.csv")] == ["45 %"]


def test_content_tables_are_byte_identical_on_a_second_run(tmp_path):
    inputs = {"tone.wav": None, "a.png": rgb_png([[9, 9, 9, 200, 200, 200]], [0]), "notes.txt": b"# Heading\n\nText 5 km.\n"}
    wav_file(tmp_path / "tone.wav", [clicks(100, rate=16000, seconds=5), sine(330, 16000, 5, 0.3)], 16000)
    for name, data in inputs.items():
        if data is not None:
            (tmp_path / name).write_bytes(data)
        runs = []
        for run in ("a", "b"):
            out = tmp_path / f"{name}-{run}"
            decompose_file(str(tmp_path / name), str(out))
            runs.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()})
        assert runs[0] == runs[1] and {"components.csv", "components.jsonl", "tree.json"} <= set(runs[0]), name


def test_cli_no_content_writes_the_tree_only(tmp_path, capsys):
    path = wav_file(tmp_path / "t.wav", [sine(440, 8000, 1)], 8000)
    assert main(["decompose", path, "--out", str(tmp_path / "bare"), "--no-content"]) == 0
    assert sorted(p.name for p in (tmp_path / "bare").iterdir()) == ["parts", "tree.json"]
    assert main(["decompose", path, "--out", str(tmp_path / "full"), "--json"]) == 0
    capsys.readouterr()
    assert {"audio_measurements.csv", "audio_spectrum.csv", "components.csv", "container.csv"} <= {
        p.name for p in (tmp_path / "full").iterdir()}
