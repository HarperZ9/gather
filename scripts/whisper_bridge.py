"""Whisper-CLI-compatible bridge for `gather transcribe`, over the installed faster_whisper.

A bridge, not ours: faster_whisper 1.2.1 (SYSTRAN) with the large-v3 weights. Gather's own
speech path is planned to replace it.

Settings are fixed so results repeat: beam 5, temperature 0, no previous-text conditioning,
the built-in voice filter on. Accepts the arguments Gather passes:
    <audio> --model NAME --output_format txt --output_dir DIR

Configuration, all by environment (no machine-specific defaults):
    GATHER_WHISPER_PYTHON  a Python with faster_whisper installed (used by whisper_bridge.cmd)
    GATHER_WHISPER_CACHE   the model cache holding the converted weights (offline: no download)
    GATHER_FFMPEG          an ffmpeg binary for decoding (default: ffmpeg on PATH)
    GATHER_WHISPER_DEVICE  cpu (default, int8) or cuda
Then point GATHER_WHISPER at whisper_bridge.cmd, and let those names through Gather's child
environment allowlist:
    GATHER_CHILD_ENV=GATHER_WHISPER_PYTHON,GATHER_WHISPER_CACHE,GATHER_FFMPEG,GATHER_WHISPER_DEVICE
"""
import argparse
import os
import sys

MODELS = {"large-v3": "Systran/faster-whisper-large-v3"}
CACHE = os.environ.get("GATHER_WHISPER_CACHE")
FFMPEG = os.environ.get("GATHER_FFMPEG", "ffmpeg")


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--output_format", default="txt")
    p.add_argument("--output_dir", default=".")
    p.add_argument("--device", default=os.environ.get("GATHER_WHISPER_DEVICE", "cpu"))
    a = p.parse_args(argv)
    if a.output_format != "txt":
        sys.stderr.write("only txt output is supported\n")
        return 2
    import subprocess
    import numpy as np
    from faster_whisper import WhisperModel
    # Decode with the installed ffmpeg binary: the venv's PyAV is a version faster_whisper's own
    # decoder cannot call. 16 kHz mono float32, which is what the model consumes.
    ffmpeg = FFMPEG
    out = os.path.join(a.output_dir, os.path.splitext(os.path.basename(a.audio))[0] + ".txt")
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", a.audio, "-vn", "-f", "f32le", "-ac", "1",
                           "-ar", "16000", "-"], capture_output=True)
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size == 0:
        # A video with no sound track is a result, not a failure: record it as such.
        with open(out, "w", encoding="utf-8") as f:
            f.write("[no audio stream]\n")
        return 0
    name = MODELS.get(a.model, MODELS["large-v3"])  # one pinned model, whatever Gather asks for
    # CPU int8 by default: the GPU path needs cublas64_12.dll, which this venv does not ship.
    model = WhisperModel(name, device=a.device, compute_type="int8" if a.device == "cpu" else "default",
                         download_root=CACHE, local_files_only=True)
    segments, _info = model.transcribe(audio, beam_size=5, temperature=0.0,
                                       condition_on_previous_text=False, vad_filter=True)
    text = "\n".join(s.text.strip() for s in segments)
    out = os.path.join(a.output_dir, os.path.splitext(os.path.basename(a.audio))[0] + ".txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
