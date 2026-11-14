"""The record every decompose handler writes, and the byte sources the handlers read.

A tree is nodes. Each node covers a byte range of its parent: ``kind``, ``offset`` and ``length``
in the parent, ``sha256`` of the range, ``params``, ``produced_by`` (handler name and version),
and either ``children`` or the bytes themselves (``hex`` up to 32 bytes, else ``blob``, a file
named by its SHA-256 under ``parts/``). Children cover their parent with no gap and no overlap;
``Maker.cover`` fills every range a handler did not claim with a ``raw`` node, so concatenating
the leaves in order always gives the original bytes back.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass

TREE_FORMAT = "gather.decompose-tree/1"
INLINE_MAX = 32
_CHUNK = 1 << 20


@dataclass
class Limits:
    """Bounds on nesting and expansion, written into every tree."""

    max_depth: int = 4
    max_entry_bytes: int = 64 << 20
    max_total_bytes: int = 256 << 20
    max_units: int = 20000
    max_text_bytes: int = 16 << 20

    def record(self) -> dict:
        return {"max_depth": self.max_depth, "max_entry_bytes": self.max_entry_bytes,
                "max_total_bytes": self.max_total_bytes, "max_units": self.max_units,
                "max_text_bytes": self.max_text_bytes}


class Source:
    """Random access to a file or to bytes held in memory. Reads never run past the end."""

    def __init__(self, stream, size: int):
        self._f = stream
        self.size = size

    @classmethod
    def of(cls, data: bytes) -> Source:
        return cls(io.BytesIO(data), len(data))

    def read(self, offset: int, length: int) -> bytes:
        self._f.seek(offset)
        return self._f.read(max(0, min(length, self.size - offset)))

    def chunks(self, offset: int, length: int):
        end = min(self.size, offset + length)
        while offset < end:
            data = self.read(offset, min(_CHUNK, end - offset))
            if not data:
                return
            yield data
            offset += len(data)

    def digest(self, offset: int, length: int) -> str:
        h = hashlib.sha256()
        for data in self.chunks(offset, length):
            h.update(data)
        return h.hexdigest()


class Context:
    """One decompose run: where blobs go, the limits, and the bytes expanded so far."""

    def __init__(self, out: str, limits: Limits):
        self.parts = os.path.join(out, "parts")
        self.limits = limits
        self.expanded = 0

    def store(self, src: Source, start: int, length: int, sha: str) -> None:
        path = os.path.join(self.parts, sha)
        if os.path.exists(path):
            return
        os.makedirs(self.parts, exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            for data in src.chunks(start, length):
                f.write(data)
        os.replace(path + ".tmp", path)


class Maker:
    """Builds nodes for one handler over one source. Offsets passed in are absolute in the source."""

    def __init__(self, src: Source, handler: str):
        self.src = src
        self.handler = handler

    def leaf(self, kind: str, start: int, length: int, **params) -> dict:
        if start < 0 or length < 0 or start + length > self.src.size:
            raise ValueError(f"{kind} runs past the end of the data")
        return {"kind": kind, "_start": start, "length": length, "sha256": self.src.digest(start, length),
                "params": params, "produced_by": self.handler}

    def group(self, kind: str, children: list[dict], **params) -> dict:
        """A node over children that are already in order and touch each other."""
        if not children:
            raise ValueError(f"{kind} has no parts")
        start = pos = children[0]["_start"]
        for child in children:
            if child["_start"] != pos:
                raise ValueError(f"{kind}: parts overlap or leave a gap")
            pos += child["length"]
        return {"kind": kind, "_start": start, "length": pos - start, "sha256": self.src.digest(start, pos - start),
                "params": params, "produced_by": self.handler, "children": children}

    def cover(self, kind: str, start: int, end: int, parts: list[dict], **params) -> dict:
        """A node over ``start..end``: the parts in offset order, with ``raw`` nodes in every gap."""
        children: list[dict] = []
        pos = start
        for part in sorted(parts, key=lambda p: p["_start"]):
            if part["_start"] < pos:
                raise ValueError(f"{kind}: parts overlap")
            if part["_start"] > pos:
                children.append(self.leaf("raw", pos, part["_start"] - pos))
            children.append(part)
            pos = part["_start"] + part["length"]
        if pos > end:
            raise ValueError(f"{kind}: parts run past the end")
        if pos < end or not children:
            children.append(self.leaf("raw", pos, end - pos))
        return self.group(kind, children, **params)


def finalize(ctx: Context, src: Source, node: dict, parent_start: int = 0) -> dict:
    """Turn absolute starts into offsets in the parent and attach each leaf's bytes."""
    start = node.pop("_start")
    out = {"kind": node["kind"], "offset": start - parent_start, "length": node["length"], "sha256": node["sha256"],
           "params": node["params"], "produced_by": node["produced_by"]}
    if "children" in node:
        out["children"] = [finalize(ctx, src, child, start) for child in node["children"]]
    elif node["length"] <= INLINE_MAX:
        out["hex"] = src.read(start, node["length"]).hex()
    else:
        ctx.store(src, start, node["length"], node["sha256"])
        out["blob"] = node["sha256"]
    if "derived" in node:
        out["derived"] = node["derived"]
    return out


def raw_ranges(node: dict, base: int = 0) -> list[dict]:
    """Every ``raw`` leaf in a finalized tree, as absolute offset and length."""
    start = base + node["offset"]
    if "children" not in node:
        return [{"offset": start, "length": node["length"]}] if node["kind"] == "raw" else []
    return [r for child in node["children"] for r in raw_ranges(child, start)]
