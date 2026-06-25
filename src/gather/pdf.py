from __future__ import annotations

import os
import subprocess
import time

from gather.item import Item, make_item


def pdf_item(name: str, text: str, *, fetched_at: float, ref: str, method: str = "pdftotext") -> Item:
    """Build one paper Item from already-extracted PDF text. Pure: no subprocess, no disk."""
    return make_item(
        kind="paper", id=name, title=name, text=text,
        source="pdf", ref=ref, method=method, fetched_at=fetched_at,
    )


class PdfSource:
    """Local PDF text intake via the ``pdftotext`` CLI (poppler-utils).

    The isolated external-tool edge, the way the video adapter shells out to ``yt-dlp``:
    pdftotext is an external program, not a Python dependency. The extracted text is a
    best-effort reading; a scanned (image-only) PDF yields little or nothing, and layout can
    reorder columns. The receipt's "pdftotext" method records that this is a tool's reading of
    the file, not the authoritative document, so a thin extraction is never mistaken for the
    full content. fetch() needs pdftotext on PATH.
    """

    name = "pdf"

    def __init__(self, *, clock=time.time, pdftotext: str = "pdftotext", timeout: float = 120.0) -> None:
        self._clock = clock
        self._pdftotext = pdftotext
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        if not os.path.isfile(target):
            raise FileNotFoundError(f"no such file: {target}")
        proc = subprocess.run(
            [self._pdftotext, "-q", "-enc", "UTF-8", "--", target, "-"],
            capture_output=True, timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        text = proc.stdout.decode("utf-8", "replace")
        return [pdf_item(os.path.basename(target), text, fetched_at=float(self._clock()), ref=os.path.realpath(target))]
