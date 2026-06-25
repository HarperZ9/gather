from __future__ import annotations

import os
import time

from gather.item import Item, make_item

TEXT_EXTENSIONS = (".txt", ".md", ".rst", ".markdown", ".text")


def document_item(name: str, text: str, *, fetched_at: float, ref: str, method: str = "file-read") -> Item:
    """Build one document Item from already-read text. Pure: no disk, no network."""
    return make_item(
        kind="document", id=name, title=name, text=text,
        source="docs", ref=ref, method=method, fetched_at=fetched_at,
    )


class DocsSource:
    """Local document intake: read a text file, or walk a directory of them.

    The impure edge here is the filesystem, not the network. ``fetch(path)`` reads one file
    (any extension) or, for a directory, every text file under it (by extension), each into a
    document Item with a provenance receipt. Deterministic: directory entries are sorted, so
    the same tree yields the same order. Symlinked directories are not descended into (no walk
    loops), and a file's ``ref`` records its resolved real path, so a symlinked source is
    attributed to where it actually lives. Files that cannot be decoded as UTF-8 are read with
    replacement rather than skipped silently: the receipt then faithfully fingerprints text
    that is itself an imperfect reading of a non-text file, so point this at text.
    """

    name = "docs"

    def __init__(self, *, clock=time.time, extensions: tuple[str, ...] = TEXT_EXTENSIONS) -> None:
        self._clock = clock
        self._extensions = extensions

    def fetch(self, target: str) -> list[Item]:
        at = float(self._clock())
        if os.path.isdir(target):
            items: list[Item] = []
            for root, dirs, files in os.walk(target):
                dirs.sort()
                for fname in sorted(files):
                    if fname.lower().endswith(self._extensions):
                        path = os.path.join(root, fname)
                        rel = os.path.relpath(path, target).replace(os.sep, "/")
                        items.append(self._read(path, name=rel, at=at))
            return items
        if not os.path.isfile(target):
            raise FileNotFoundError(f"no such file or directory: {target}")
        return [self._read(target, name=os.path.basename(target), at=at)]

    def _read(self, path: str, *, name: str, at: float) -> Item:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return document_item(name, text, fetched_at=at, ref=os.path.realpath(path))
