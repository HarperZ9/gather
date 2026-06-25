from __future__ import annotations

import glob
import os
import subprocess
import tempfile
import time

from gather.item import Item, make_item


def transcribe_item(name: str, text: str, *, fetched_at: float, ref: str, method: str = "transcribe") -> Item:
    """Build one transcript Item from already-transcribed text. Pure: no subprocess, no disk."""
    return make_item(
        kind="transcript", id=name, title=name, text=text,
        source="transcribe", ref=ref, method=method, fetched_at=fetched_at,
    )


class TranscribeSource:
    """A transcript from an audio file via a Whisper-style speech-to-text CLI. The isolated
    external-tool edge for audio.

    Shells out to ``whisper`` (an external tool, not a Python dependency), writing the transcript
    into a temp directory and reading it back, the way the video adapter handles captions. The
    receipt's ``transcribe`` method records that this is a machine transcription, not a manual one,
    so its errors are on the record. The audio path is resolved to an absolute path before it is
    passed to the tool, so a filename starting with ``-`` cannot be read as a flag. fetch() needs
    the transcription tool on PATH.
    """

    name = "transcribe"

    def __init__(self, *, clock=time.time, whisper: str = "whisper", model: str = "base",
                 timeout: float = 600.0) -> None:
        self._clock = clock
        self._whisper = whisper
        self._model = model
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        if not os.path.isfile(target):
            raise FileNotFoundError(f"no such audio file: {target}")
        path = os.path.abspath(target)  # absolute path cannot be parsed as a flag
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [self._whisper, path, "--model", self._model, "--output_format", "txt", "--output_dir", d],
                capture_output=True, timeout=self._timeout,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"whisper failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
            txts = sorted(glob.glob(os.path.join(d, "*.txt")))
            if not txts:
                raise RuntimeError("whisper produced no transcript")
            with open(txts[0], encoding="utf-8", errors="replace") as f:
                text = f.read()
        return [transcribe_item(os.path.basename(target), text, fetched_at=float(self._clock()),
                                ref=os.path.realpath(target))]
