"""The decompose front door: any local file in, one tree out.

``decompose_file(path, out)`` hashes the file, picks handlers from its bytes (never its
extension), and writes ``tree.json`` (``gather.decompose-tree/1``) with the leaf bytes under
``parts/``. A handler that cannot read the bytes is recorded under ``declined`` and the next one
is tried; the raw handler always works, so every file gets a tree that rebuilds byte for byte.
The file is data: nothing in it is executed, no child process starts and no network is used.
"""

from __future__ import annotations

import json
import os
import struct

from gather.decompose_binary import PNG_SIGNATURE, build_png, build_raw, build_wav
from gather.decompose_content import content_stage
from gather.decompose_text import build_json, build_sidecar, build_text, load_text
from gather.decompose_tree import (
    TREE_FORMAT,
    Context,
    Limits,
    Maker,
    Source,
    finalize,
    raw_ranges,
)
from gather.decompose_zip import build_zip

_DECLINE = (ValueError, struct.error, IndexError, RecursionError)


def _zip(m: Maker, ctx: Context, depth: int) -> dict:
    return build_zip(m, ctx, depth, decompose_bytes)


def candidates(src: Source, ctx: Context) -> list[tuple[str, object]]:
    """Handlers to try, in order, chosen from the first bytes. The raw handler is always last."""
    head = src.read(0, 16)
    found: list[tuple[str, object]] = []
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        found.append(("zip/1", _zip))
    elif head[:8] == PNG_SIGNATURE:
        found.append(("png/1", build_png))
    elif head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        found.append(("wav/1", build_wav))
    elif src.size:
        try:
            data, bom = load_text(Maker(src, "text/1"), ctx)
        except ValueError:
            data = None
        if data is not None:
            if data[bom:].startswith(b"---"):
                found.append(("cmmns-sidecar/1", build_sidecar))
            found += [("json/1", build_json), ("text/1", build_text)]
    return found + [("raw/1", build_raw)]


def decompose_source(ctx: Context, src: Source, depth: int) -> dict:
    """The tree for one source: bytes, hash, the handler that built it, and the ones that declined."""
    declined: list[dict] = []
    for handler, build in candidates(src, ctx):
        try:
            node = build(Maker(src, handler), ctx, depth)  # type: ignore[operator]
        except _DECLINE as exc:
            declined.append({"handler": handler, "reason": str(exc)})
            continue
        root = finalize(ctx, src, node)
        return {"bytes": src.size, "sha256": root["sha256"], "handler": handler, "declined": declined,
                "rebuild": "exact", "unparsed": raw_ranges(root), "root": root}
    raise ValueError("no handler built a tree")  # the raw handler makes this unreachable


def decompose_bytes(ctx: Context, data: bytes, depth: int) -> dict:
    return decompose_source(ctx, Source.of(data), depth)


def _companion(ctx: Context, path: str) -> list[dict]:
    """The JSON sidecar beside a CMMNS Markdown sidecar, as its own rebuildable tree."""
    stem, ext = os.path.splitext(path)
    other = stem + ".json"
    if ext.lower() != ".md" or not os.path.isfile(other):
        return []
    with open(other, "rb") as f:
        tree = decompose_source(ctx, Source(f, os.path.getsize(other)), 0)
    return [{"name": os.path.basename(other), **tree}]


def write_tree(out: str, doc: dict) -> None:
    with open(os.path.join(out, "tree.json"), "wb") as f:
        f.write((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def decompose_file(path: str, out: str, limits: Limits | None = None, content: bool = True) -> dict:
    """Write the tree for ``path`` into ``out`` and return it. ``content`` adds the measurement tables.

    Raises ValueError when ``path`` is not a file or ``out`` already holds files, and OSError
    when the file cannot be read.
    """
    if not os.path.isfile(path):
        raise ValueError("the input is not a file")
    if os.path.isdir(out) and os.listdir(out):
        raise ValueError("--out already holds files; give an empty or new folder")
    os.makedirs(out, exist_ok=True)
    ctx = Context(out, limits or Limits())
    with open(path, "rb") as f:
        tree = decompose_source(ctx, Source(f, os.path.getsize(path)), 0)
    doc = {"format": TREE_FORMAT, "source": {"name": os.path.basename(path), "bytes": tree.pop("bytes"),
                                             "sha256": tree.pop("sha256")},
           "limits": ctx.limits.record(), **tree}
    if doc["handler"] == "cmmns-sidecar/1":
        doc["companions"] = _companion(ctx, path)
    if content:
        doc["content"] = content_stage(path, out)
    write_tree(out, doc)
    return doc
