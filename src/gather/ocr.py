from __future__ import annotations

import os
import subprocess
import time

from gather.item import Item, make_item


def ocr_item(name: str, text: str, *, fetched_at: float, ref: str, method: str = "ocr") -> Item:
    """Build one document Item from already-recognized text. Pure: no subprocess, no disk."""
    return make_item(
        kind="document", id=name, title=name, text=text,
        source="ocr", ref=ref, method=method, fetched_at=fetched_at,
    )


class OcrSource:
    """Text from a scanned image via the ``tesseract`` OCR engine. The isolated external-tool edge
    for scans and photographs of text.

    Shells out to ``tesseract`` (an external tool, not a Python dependency). The recognized text is
    a best-effort reading: OCR makes mistakes, especially on poor scans, and the receipt's ``ocr``
    method records that this is a machine reading of an image, not a transcript of a text source,
    so a noisy read is never mistaken for the real words. The image path is resolved to an absolute
    path before it is passed to the tool, so a filename starting with ``-`` cannot be read as a
    flag. fetch() needs tesseract on PATH.
    """

    name = "ocr"

    def __init__(self, *, clock=time.time, tesseract: str = "tesseract", lang: str = "eng",
                 timeout: float = 120.0) -> None:
        self._clock = clock
        self._tesseract = tesseract
        self._lang = lang
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        if not os.path.isfile(target):
            raise FileNotFoundError(f"no such image file: {target}")
        path = os.path.abspath(target)  # absolute path cannot be parsed as a flag by tesseract
        proc = subprocess.run(
            [self._tesseract, path, "stdout", "-l", self._lang],
            capture_output=True, timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        text = proc.stdout.decode("utf-8", "replace")
        return [ocr_item(os.path.basename(target), text, fetched_at=float(self._clock()),
                         ref=os.path.realpath(target))]
