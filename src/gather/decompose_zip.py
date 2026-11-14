"""Structural handler for ZIP archives.

The archive is read from its end record: the central directory, then each entry's local header,
its compressed bytes and its data descriptor. Compressed bytes are kept as they are and never
recompressed, so the rebuild is exact. Each entry is also inflated into memory, within the
limits, and that decoded copy is decomposed by the front door and attached as ``derived``; the
rebuild never reads it. An entry name is recorded in the tree and never used as an output path.
ZIP64, split archives and encrypted entries are not expanded; ZIP64 archives fall back to raw.
"""

from __future__ import annotations

import struct
import zlib

from gather.decompose_tree import Maker

_EOCD, _CENTRAL, _LOCAL, _DESCRIPTOR = b"PK\x05\x06", b"PK\x01\x02", b"PK\x03\x04", b"PK\x07\x08"
_MAX_ENTRIES = 50000
_METHODS = {0: "stored", 8: "deflate"}


def _end_record(m: Maker) -> tuple[int, int, int, int]:
    """(offset of the end record, entry count, central directory size, central directory offset)."""
    size = m.src.size
    tail_start = max(0, size - 65557)
    tail = m.src.read(tail_start, size - tail_start)
    at = tail.rfind(_EOCD)
    while at >= 0:
        if at + 22 <= len(tail):
            entries, cd_size, cd_offset, comment = struct.unpack("<HIIH", tail[at + 10:at + 22])
            if at + 22 + comment <= len(tail):
                break
        at = tail.rfind(_EOCD, 0, at)
    if at < 0:
        raise ValueError("no end-of-central-directory record")
    if entries == 0xFFFF or cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        raise ValueError("ZIP64 archives are not handled yet")
    if entries > _MAX_ENTRIES:
        raise ValueError("more entries than the handler's limit")
    return tail_start + at, entries, cd_size, cd_offset


def _name(raw: bytes, flags: int) -> str:
    return raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")


def _central(m: Maker, pos: int) -> tuple[dict, dict]:
    """(node, facts) for the central directory header at ``pos``."""
    fixed = m.src.read(pos, 46)
    (sig, _, _, flags, method, _, _, crc, csize, usize, nlen, elen, clen, _, _, _, local) = struct.unpack(
        "<4s6H3I5H2I", fixed)
    if sig != _CENTRAL:
        raise ValueError("central directory header expected")
    if 0xFFFFFFFF in (csize, usize, local):
        raise ValueError("ZIP64 entries are not handled yet")
    name = _name(m.src.read(pos + 46, nlen), flags)
    facts = {"name": name, "flags": flags, "method": method, "crc32": f"{crc:08x}", "compressed_size": csize,
             "size": usize, "local_offset": local}
    fields = [m.leaf("fixed-fields", pos, 46)]
    for kind, length in (("name", nlen), ("extra", elen), ("comment", clen)):
        if length:
            start = fields[-1]["_start"] + fields[-1]["length"]
            fields.append(m.leaf(kind, start, length))
    return m.group("zip-central-header", fields, **facts), facts


def _expand(m: Maker, ctx, depth: int, start: int, facts: dict, decompose) -> dict:
    """The entry's decoded bytes as a derived tree, or the reason they were not expanded."""
    limits = ctx.limits
    method = _METHODS.get(facts["method"])
    reasons = ((facts["flags"] & 1, "encrypted"), (method is None, "compression method not handled"),
               (depth + 1 > limits.max_depth, "nesting depth limit"),
               (max(facts["compressed_size"], facts["size"]) > limits.max_entry_bytes, "larger than the per-entry limit"),
               (ctx.expanded + facts["size"] > limits.max_total_bytes, "total expansion limit reached"))
    for hit, reason in reasons:
        if hit:
            return {"method": method or "unknown", "status": f"not expanded ({reason})"}
    data = m.src.read(start, facts["compressed_size"])
    if method == "deflate":
        try:
            data = zlib.decompressobj(-15).decompress(data, limits.max_entry_bytes + 1)
        except zlib.error:
            return {"method": method, "status": "not expanded (deflate stream is damaged)"}
        if len(data) > limits.max_entry_bytes:
            return {"method": method, "status": "not expanded (larger than the per-entry limit)"}
    ctx.expanded += len(data)
    ok = f"{zlib.crc32(data):08x}" == facts["crc32"] and len(data) == facts["size"]
    return {"method": method, "status": "ok" if ok else "expanded; size or CRC differs from the header",
            **decompose(ctx, data, depth + 1)}


def _entry(m: Maker, facts: dict) -> dict:
    """One entry's local header, compressed bytes and data descriptor."""
    pos = facts["local_offset"]
    fixed = m.src.read(pos, 30)
    sig, _, flags, _, _, _, _, _, _, nlen, elen = struct.unpack("<4s5H3I2H", fixed)
    if sig != _LOCAL:
        raise ValueError("local file header expected")
    header = [m.leaf("fixed-fields", pos, 30)]
    if nlen:
        header.append(m.leaf("name", pos + 30, nlen))
    if elen:
        header.append(m.leaf("extra", pos + 30 + nlen, elen))
    facts["data_start"] = pos + 30 + nlen + elen
    parts = [m.group("zip-local-header", header)]
    if facts["compressed_size"]:
        parts.append(m.leaf("compressed-data", facts["data_start"], facts["compressed_size"], method=facts["method"]))
    after = facts["data_start"] + facts["compressed_size"]
    if flags & 8:
        length = 16 if m.src.read(after, 4) == _DESCRIPTOR else 12
        parts.append(m.leaf("data-descriptor", after, length))
    return m.group("zip-entry", parts, name=facts["name"], method=facts["method"], size=facts["size"])


def build_zip(m: Maker, ctx, depth: int, decompose) -> dict:
    """``decompose(ctx, data, depth)`` is the front door for the decoded copy of an entry.

    The structure is built and checked first; entries are expanded only once the cover holds.
    """
    if m.src.read(0, 4) not in (_LOCAL, _EOCD):
        raise ValueError("not a ZIP signature")
    end_at, count, cd_size, cd_offset = _end_record(m)
    entries: list[tuple[dict, dict]] = []
    directory: list[dict] = []
    pos = cd_offset
    for _ in range(count):
        node, facts = _central(m, pos)
        directory.append(node)
        entries.append((_entry(m, facts), facts))
        pos += node["length"]
    parts = [node for node, _ in entries]
    if directory:
        parts.append(m.group("zip-central-directory", directory, entries=count))
    parts.append(m.leaf("zip-end-record", end_at, m.src.size - end_at, entries=count, central_directory_size=cd_size,
                        central_directory_offset=cd_offset))
    root = m.cover("zip", 0, m.src.size, parts, entries=count)
    for node, facts in entries:
        if facts["size"]:
            node["derived"] = _expand(m, ctx, depth, facts["data_start"], facts, decompose)
    return root
