"""Whisper-CLI-compatible bridge for `gather transcribe`, over the installed faster_whisper.

Bridge, not ours: faster_whisper 1.2.1 (SYSTRAN) with the large-v3 weights at
E:/hf-cache/hub/models--Systran--faster-whisper-large-v3. Our replacement is planned in
mission-control/2026-11-14-video-parse/OWN-SPEECH-PLAN.md.

Settings are fixed so results repeat: beam 5, temperature 0, no previous-text conditioning,
the built-in voice filter on. Accepts the arguments Gather passes:
    <audio> --model NAME --output_format txt --output_dir DIR
Run with D:/venvs/voice/Scripts/python.exe; point GATHER_WHISPER at whisper_bridge.cmd.
"""
import argparse
import os
import sys

MODELS = {"large-v3": "Systran/faster-whisper-large-v3"}
CACHE = os.environ.get("GATHER_WHISPER_CACHE", "E:/hf-cache/hub")
FFMPEG = ("C:/Users/Zain/AppData/Local/Programs/Python/Python312/Lib/site-packages/"
          "imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe")


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
    ffmpeg = os.environ.get("GATHER_FFMPEG", FFMPEG)
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", a.audio, "-f", "f32le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        sys.stderr.write("no audio stream decoded\n")
        return 3
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
