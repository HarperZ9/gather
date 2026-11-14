"""Write the saves tables: CSV, JSON Lines and the manifest, the same bytes on every platform.

CSV is UTF-8 without a BOM, ``\\n`` line endings, minimal quoting. JSON Lines keeps the column
order. Every file is written as bytes, so the platform never changes a line ending. The manifest
holds row counts and the SHA-256 of each table, with no time, host name or absolute path.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os

MANIFEST_FORMAT = "gather.saves-tables/1"


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def csv_bytes(columns: tuple, rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    writer.writerows([_cell(row[c]) for c in columns] for row in rows)
    return buf.getvalue().encode("utf-8")


def jsonl_bytes(columns: tuple, rows: list[dict]) -> bytes:
    lines = (json.dumps({c: row[c] for c in columns}, ensure_ascii=False, sort_keys=False) for row in rows)
    return "".join(line + "\n" for line in lines).encode("utf-8")


def _write(out: str, name: str, data: bytes) -> str:
    with open(os.path.join(out, name), "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def write_outputs(out: str, tables: tuple, counts: dict) -> dict:
    """Write each table as ``<name>.csv`` and ``<name>.jsonl`` plus ``manifest.json``; return the manifest."""
    os.makedirs(out, exist_ok=True)
    manifest = {"format": MANIFEST_FORMAT, **counts, "tables": {}}
    for name, columns, rows in tables:
        for suffix, encode in ((".csv", csv_bytes), (".jsonl", jsonl_bytes)):
            digest = _write(out, name + suffix, encode(columns, rows))
            manifest["tables"][name + suffix] = {"rows": len(rows), "sha256": digest}
    _write(out, "manifest.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return manifest
