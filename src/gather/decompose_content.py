"""The content level of ``gather decompose``: measurements and estimates, kept apart from the tree.

``content_stage(path, out)`` writes ``components.csv`` and ``components.jsonl`` (one row per
component: what it is, the table that holds it, how it was produced, whether it is deterministic,
and its status) plus one table per kind. A component that needs a decoder or a tool that is not
here gets a row that says so; nothing is guessed and nothing is fetched. No child process is
started: an installed transcriber or stem separator is only detected, and its row reads
``planned``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os

from gather import __version__
from gather.decompose_document import document_tables, is_pdf
from gather.decompose_dsp import decay_time, key, spectrum, tempo
from gather.decompose_image import PALETTE_RULE, png_palette
from gather.decompose_pcm import WINDOW_RULE, integrated_loudness, levels, read_pcm, sig
from gather.media_probe import probe
from gather.saves_write import csv_bytes, jsonl_bytes
from gather.spawn import find_tool

COLUMNS = ("kind", "component", "path", "produced_by", "tool", "tool_version", "deterministic", "status", "sha256")
NO_DECODER = "not run (needs a local decoder; none in the standard library)"
NO_TOOL = "not run (tool not installed)"
MEASURED = "yes (fixed rules, rounded to 6 significant digits)"
MODEL = "no (model output; repeatable only with pinned weights, a fixed seed and one device)"
_AUDIO = (("sample peak", "largest absolute sample"), ("RMS level", "root mean square of all samples"),
          ("crest factor", "sample peak minus RMS level"), ("DC offset", "mean of all samples"),
          ("integrated loudness", "ITU-R BS.1770 K-weighting with absolute and relative gates"),
          ("tempo estimate", "onset-envelope autocorrelation, 60 to 200 BPM"),
          ("key estimate", "Goertzel chroma matched to Krumhansl and Schmuckler profiles"),
          ("spectrum summary", "averaged 4096-point FFT: octave-band energy and centroid"),
          ("decay time estimate", "Schroeder integration after the loudest frame, -5 to -25 dB fit; "
                                  "an estimate from programme material, not a room measurement"))
_VIDEO = ("shot boundaries", "keyframes", "frame rate", "colour summary per shot")


def _row(kind: str, component: str, path: str = "", how: str = "", deterministic: str = "yes",
         status: str = "ok", tool: str = "gather") -> dict:
    return {"kind": kind, "component": component, "path": path, "produced_by": how, "tool": tool,
            "tool_version": __version__ if tool == "gather" else "", "deterministic": deterministic,
            "status": status, "sha256": ""}


def _measure(name: str, value, unit: str, method: str) -> dict:
    shown = sig(value) if isinstance(value, float) else value
    return {"measure": name, "value": shown, "unit": unit, "method": method, "window": WINDOW_RULE}


def _audio_tables(path: str) -> tuple[dict, dict]:
    """(tables, status per component) for a PCM WAV. Raises ValueError when the PCM cannot be read."""
    pcm = read_pcm(path)
    mono = pcm.mono()
    level, loud = levels(pcm), integrated_loudness(pcm)
    bpm, tonic, spec = tempo(mono, pcm.rate), key(mono, pcm.rate), spectrum(mono, pcm.rate)
    decay = decay_time(mono, pcm.rate)
    how = dict(_AUDIO)
    measures = [
        _measure("frames_analysed", pcm.frames, "frames", "count"), _measure("frames_total", pcm.frames_total, "frames", "count"),
        _measure("sample_peak", level["sample_peak_dbfs"], "dBFS", how["sample peak"]),
        _measure("rms_level", level["rms_dbfs"], "dBFS", how["RMS level"]),
        _measure("crest_factor", level["crest_factor_db"], "dB", how["crest factor"]),
        _measure("dc_offset", level["dc_offset"], "full scale", how["DC offset"]),
        _measure("integrated_loudness", loud, "LUFS", how["integrated loudness"]),
        _measure("tempo_estimate", bpm, "BPM", how["tempo estimate"]),
        _measure("key_estimate", tonic[0] if tonic else None, "key", how["key estimate"]),
        _measure("key_profile_correlation", tonic[1] if tonic else None, "r", how["key estimate"]),
        _measure("spectral_centroid", spec["centroid_hz"], "Hz", how["spectrum summary"]),
        _measure("decay_time_60db_estimate", decay, "s", how["decay time estimate"])]
    bands = [{"band_centre_hz": centre, "energy_db_rel_total": None if value is None else sig(value)}
             for centre, value in spec["bands"]]
    missing = {"integrated loudness": (loud, "no 400 ms block passes the gates"),
               "tempo estimate": (bpm, "under 4 s of audio, or no onsets"), "key estimate": (tonic, "too short or silent"),
               "decay time estimate": (decay, "the tail does not fall 25 dB"),
               "sample peak": (level["sample_peak_dbfs"], "silent"), "RMS level": (level["rms_dbfs"], "silent"),
               "crest factor": (level["crest_factor_db"], "silent"), "spectrum summary": (spec["centroid_hz"], "silent")}
    status = {name: f"not run ({why})" for name, (value, why) in missing.items() if value is None}
    return {"audio_measurements.csv": (("measure", "value", "unit", "method", "window"), measures),
            "audio_spectrum.csv": (("band_centre_hz", "energy_db_rel_total"), bands)}, status


def _audio_rows(path: str, container: str, tables: dict) -> list[dict]:
    if container != "wav":
        return [_row("audio", name, how=how, deterministic=MEASURED, status=NO_DECODER) for name, how in _AUDIO]
    try:
        made, status = _audio_tables(path)
    except ValueError as exc:
        return [_row("audio", name, how=how, deterministic=MEASURED, status=f"not run ({exc})") for name, how in _AUDIO]
    tables.update(made)
    return [_row("audio", name, "audio_spectrum.csv" if name == "spectrum summary" else "audio_measurements.csv", how,
                 MEASURED, status.get(name, "ok")) for name, how in _AUDIO]


def _tool_rows(kinds: set[str]) -> list[dict]:
    """Rows for components that need a local tool: detected only, never started here."""
    rows = []
    if kinds & {"audio", "video"}:
        stems = importlib.util.find_spec("remastering") is not None and bool(os.environ.get("REMASTER_MODELS"))
        rows.append(_row("audio", "stems", how="stem separation by the remastering package (htdemucs_ft)",
                         deterministic=MODEL, status="planned" if stems else NO_TOOL, tool="remastering"))
        rows.append(_row("speech", "transcript with timestamps", how="local speech-to-text through gather.transcribe",
                         deterministic=MODEL, status="planned" if find_tool("whisper") else NO_TOOL, tool="whisper"))
    if "image" in kinds:
        rows.append(_row("image", "embedded text", how="local text recognition through gather.ocr",
                         deterministic="no (recognition engine output; version dependent)",
                         status="planned" if find_tool("tesseract") else NO_TOOL, tool="tesseract"))
    return rows


def _image_rows(path: str, container: str, tables: dict) -> list[dict]:
    how = f"pixel count per colour bin: {PALETTE_RULE}"
    if container != "png":
        status = "planned" if container == "gif" else NO_DECODER
        return [_row("image", "palette", how=how, status=status)]
    try:
        tables["image_palette.csv"] = (("rank", "colour", "pixels", "share"), png_palette(path))
    except ValueError as exc:
        return [_row("image", "palette", how=how, status=f"not run ({exc})")]
    return [_row("image", "palette", "image_palette.csv", how)]


def _rows(path: str, tables: dict) -> list[dict]:
    facts, _ = probe(path, with_hash=False)
    container, kind = facts["container"], facts["kind"]
    if container == "unknown":
        if is_pdf(path):
            return [_row("document", "text", how="local text extraction through gather.pdf", tool="pdftotext",
                         deterministic="no (tool output; version dependent)",
                         status="planned" if find_tool("pdftotext") else NO_TOOL)]
        made = document_tables(path)
        tables.update(made)
        return [_row("document", name[len("document_"):-len(".csv")].replace("_", " "), name,
                     "fixed rules over the decoded text") for name in made]
    tables["container.csv"] = (("field", "value"), [{"field": k, "value": v} for k, v in facts.items() if k != "sha256"])
    rows = [_row(kind, "container facts", "container.csv", "magic bytes and the container's own header fields")]
    if kind == "image":
        rows += _image_rows(path, container, tables)
    if kind == "video":
        rows += [_row("video", name, how="needs decoded frames", status=NO_DECODER) for name in _VIDEO]
    if kind in ("audio", "video"):
        rows += _audio_rows(path, container, tables)
    return rows + _tool_rows({kind})


def content_stage(path: str, out: str) -> list[dict]:
    """Write the content tables for ``path`` into ``out`` and return the component rows."""
    tables: dict = {}
    rows = _rows(path, tables)
    digests = {}
    for name, (columns, table_rows) in sorted(tables.items()):
        data = csv_bytes(columns, table_rows)
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        digests[name] = hashlib.sha256(data).hexdigest()
    for row in rows:
        row["sha256"] = digests.get(row["path"], "")
    for name, encode in (("components.csv", csv_bytes), ("components.jsonl", jsonl_bytes)):
        with open(os.path.join(out, name), "wb") as f:
            f.write(encode(COLUMNS, rows))
    return rows
