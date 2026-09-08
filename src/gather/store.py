from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from gather.digest import Digest, digest_of_receipts
from gather.item import Item, Provenance, content_hash

MATCH = "MATCH"        # the stored body still hashes to its receipt
MISSING = "MISSING"    # the receipt points at a body that is not in the store
CORRUPT = "CORRUPT"    # the stored body no longer hashes to its receipt
LEGACY_COMPATIBLE = "LEGACY_COMPATIBLE"  # source text reconstructed from an unwitnessed legacy object
STORAGE_SCHEMA = "gather.storage/v1"
STORAGE_CODEC_UTF8_EXACT = "utf8-exact/v1"

_HEX = set("0123456789abcdef")


def _field(row: dict, key: str) -> Any:
    """Read a required field from a catalog row, raising a clear ValueError (not a bare KeyError)
    if it is missing, since rows come from disk and can be hand-edited or an older schema."""
    try:
        return row[key]
    except KeyError as exc:
        raise ValueError(f"catalog row missing field {key!r}") from exc


def _check_sha(sha: str) -> str:
    """A content hash is exactly 64 lowercase hex chars. Reject anything else BEFORE it is used
    to build a filesystem path, so a tampered catalog cannot drive a path-traversal read."""
    if len(sha) != 64 or any(c not in _HEX for c in sha):
        raise ValueError(f"not a valid content hash: {sha[:48]!r}")
    return sha


def _receipt_key_from_row(row: dict) -> tuple:
    return (row["kind"], row["id"], row["title"], row["source"], row["ref"],
            row["method"], row["sha256"], tuple(row.get("derived_from") or []))


def _receipt_key_from_item(item: Item) -> tuple:
    p = item.provenance
    return (item.kind, item.id, item.title, p.source, p.ref, p.method, p.sha256, p.derived_from)


def stored_rows_for_items(rows: Iterable[dict], items: Sequence[Item]) -> list[dict]:
    """Return the stored catalog row for each item receipt, preserving item order."""
    by_key: dict[tuple, dict] = {}
    for row in rows:
        by_key.setdefault(_receipt_key_from_row(row), row)
    out: list[dict] = []
    for item in items:
        key = _receipt_key_from_item(item)
        if key not in by_key:
            raise ValueError(f"stored row missing for item {item.id!r}")
        out.append(dict(by_key[key]))
    return out


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _storage_witness(raw: bytes) -> dict[str, str]:
    return {
        "schema": STORAGE_SCHEMA,
        "codec": STORAGE_CODEC_UTF8_EXACT,
        "object_sha256": _sha_bytes(raw),
    }


def _check_storage_witness(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("storage witness is not an object")
    schema = value.get("schema")
    codec = value.get("codec")
    object_sha = value.get("object_sha256")
    if schema != STORAGE_SCHEMA:
        raise ValueError("storage witness schema must be gather.storage/v1")
    if codec != STORAGE_CODEC_UTF8_EXACT:
        raise ValueError("storage witness codec must be utf8-exact/v1")
    if not isinstance(object_sha, str) or len(object_sha) != 64 or any(c not in _HEX for c in object_sha):
        raise ValueError("storage witness object_sha256 must be a sha256 hex digest")
    return {"schema": schema, "codec": codec, "object_sha256": object_sha}


def _legacy_windows_text_candidates(raw: bytes) -> list[str]:
    decoded = raw.decode("utf-8")
    candidates = [decoded]
    legacy_inverse = decoded.replace("\r\n", "\n")
    if legacy_inverse != decoded:
        candidates.append(legacy_inverse)
    return candidates


@dataclass(frozen=True, slots=True)
class StoredText:
    status: str
    text: str | None = None
    sha256: str = ""
    object_sha256: str = ""
    storage: dict[str, str] | None = None
    storage_status: str = ""
    storage_witnessed: bool = False


def verify_stored_text(raw: bytes, sha256: str, storage: object | None = None) -> StoredText:
    """Verify object bytes against a source-text receipt and optional exact-storage witness.

    Rows written by the exact UTF-8 writer carry ``storage`` and must match both the stored
    object bytes and source-text hash. Legacy rows without that witness are decoded with a
    bounded compatibility candidate set: exact UTF-8, plus the inverse of the old Windows text
    writer's LF-to-CRLF expansion. That reconstructs source text only; it does not prove old raw
    object-byte integrity.
    """
    try:
        expected = _check_sha(sha256)
    except ValueError:
        return StoredText(CORRUPT, sha256=sha256)
    object_sha = _sha_bytes(raw)
    try:
        checked_storage = _check_storage_witness(storage)
    except ValueError:
        return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                          storage_status=CORRUPT, storage_witnessed=True)
    if checked_storage is not None:
        if checked_storage["object_sha256"] != object_sha:
            return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                              storage=checked_storage, storage_status=CORRUPT,
                              storage_witnessed=True)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                              storage=checked_storage, storage_status=CORRUPT,
                              storage_witnessed=True)
        if content_hash(text) != expected:
            return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                              storage=checked_storage, storage_status=CORRUPT,
                              storage_witnessed=True)
        return StoredText(MATCH, text=text, sha256=expected, object_sha256=object_sha,
                          storage=checked_storage, storage_status=MATCH, storage_witnessed=True)
    try:
        candidates = _legacy_windows_text_candidates(raw)
    except UnicodeDecodeError:
        return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                          storage_status=CORRUPT, storage_witnessed=False)
    matches: list[str] = []
    for candidate in candidates:
        if content_hash(candidate) == expected and candidate not in matches:
            matches.append(candidate)
    if len(matches) != 1:
        return StoredText(CORRUPT, sha256=expected, object_sha256=object_sha,
                          storage_status=CORRUPT, storage_witnessed=False)
    return StoredText(MATCH, text=matches[0], sha256=expected, object_sha256=object_sha,
                      storage_status=LEGACY_COMPATIBLE, storage_witnessed=False)


class Corpus:
    """A content-addressed, re-verifiable store of gathered items.

    Layout under ``root``: ``objects/ab/cdef...`` holds each item's body keyed by the sha256 of
    its exact source text, so identical content is stored once (the natural dedup);
    ``catalog.jsonl`` is an append log of one row per DISTINCT receipt. New writes use exact
    UTF-8 bytes and carry a versioned storage witness in the catalog row. Crucially the dedup is
    at the body level only:
    two different items with byte-identical text (different source, ref, or method) keep BOTH
    receipts and share one body, so no provenance is ever dropped. Re-adding an item whose whole
    receipt already exists is the no-op that is deduped.

    Because a body lives at the address of its own source-text hash, the store is self-verifying:
    ``verify`` re-hashes every stored body and reports MATCH, MISSING, or CORRUPT, making the
    digest's proof-over-trust durable over a growing corpus. Rows without a storage witness use
    bounded legacy source-text reconstruction; they do not claim historical raw-byte integrity.

    Efficiency and durability: content-addressing dedups bodies; bodies are read one at a time
    (``verify`` never holds them all in memory), though the small receipt rows are collected to
    compute a seal. With ``fsync`` (the default) each body and the catalog are flushed to disk so
    the word "durable" is earned; pass ``fsync=False`` for a faster bulk load that trades that
    guarantee. ``add`` scans the existing catalog once to dedup against it, so it assumes a single
    writer at a time.
    """

    def __init__(self, root: str, *, fsync: bool = True) -> None:
        self._root = root
        self._objects = os.path.join(root, "objects")
        self._catalog = os.path.join(root, "catalog.jsonl")
        self._runs = os.path.join(root, "runs.jsonl")
        self._fsync = fsync

    def _object_path(self, sha: str) -> str:
        v = _check_sha(sha)  # validate once, then build both path parts from the validated value
        return os.path.join(self._objects, v[:2], v[2:])

    def _write_object(self, text: str) -> tuple[str, bool, dict[str, str] | None]:
        """Write a body addressed by its hash. Returns ``(sha, is_new, storage)``; an existing
        body is a no-op (dedup). Written to a temp file then renamed, so a body is never
        half-present."""
        raw = text.encode("utf-8")
        sha = _sha_bytes(raw)
        storage = _storage_witness(raw)
        path = self._object_path(sha)
        if os.path.exists(path):
            with open(path, "rb") as f:
                existing = f.read()
            if _sha_bytes(existing) == storage["object_sha256"]:
                return sha, False, storage
            legacy = verify_stored_text(existing, sha, None)
            if legacy.status == MATCH:
                return sha, False, None
            raise ValueError("preexisting object does not match receipt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
        return sha, True, storage

    @staticmethod
    def _key(row: dict) -> tuple:
        """The identity of a receipt: its sealed fields (not fetched_at or meta). Two rows with
        the same key are the same item, so re-adding one is a no-op."""
        return _receipt_key_from_row(row)

    def add(self, items: list[Item]) -> dict[str, int]:
        """Add items. Returns counts ``{added, deduped, total}``.

        Every distinct receipt is appended (so provenance is never dropped); a body already
        present is reused, and an item whose whole receipt already exists is deduped. ``meta`` must
        be JSON-serializable. Each call scans the existing catalog once to dedup against it, so the
        cost is O(catalog size) per call (O(K x N) over K incremental adds); for a bulk load, batch
        items into one ``add``. Memory stays flat (the catalog streams). Single-writer.
        """
        os.makedirs(self._root, exist_ok=True)
        seen = {self._key(r) for r in self.rows()}
        added = deduped = 0
        with open(self._catalog, "a", encoding="utf-8") as cat:
            for it in items:
                sha, _is_new, storage = self._write_object(it.text)  # dedups the body
                if sha != it.provenance.sha256:
                    raise ValueError(f"item {it.id!r} content hash does not match its provenance")
                row = self._row(it, storage=storage)
                key = self._key(row)
                if key in seen:
                    deduped += 1
                    continue
                seen.add(key)
                try:
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                except TypeError as exc:
                    raise ValueError(f"item {it.id!r} has non-JSON-serializable meta: {exc}") from exc
                cat.write(line + "\n")
                added += 1
            cat.flush()
            if self._fsync:
                os.fsync(cat.fileno())
        if self._fsync:
            self._fsync_dir(self._root)
        return {"added": added, "deduped": deduped, "total": len(items)}

    @staticmethod
    def _fsync_dir(path: str) -> None:
        if os.name != "posix":  # opening a directory for fsync is POSIX-only
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _row(it: Item, *, storage: dict[str, str] | None = None) -> dict[str, Any]:
        p = it.provenance
        row = {
            "kind": it.kind, "id": it.id, "title": it.title,
            "source": p.source, "ref": p.ref, "method": p.method,
            "sha256": p.sha256, "derived_from": list(p.derived_from),
            "fetched_at": p.fetched_at, "meta": it.meta,
        }
        if storage is not None:
            row["storage"] = storage
        return row

    @staticmethod
    def _stream_jsonl(path: str, what: str) -> Iterator[dict]:
        """Stream a JSONL file one row at a time. A malformed line raises a located ValueError
        rather than a silent skip (an accountable store surfaces corruption, it does not hide it)."""
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"corpus {what} line {n} is not valid JSON: {exc}") from exc

    def rows(self) -> Iterator[dict]:
        """Stream the catalog rows (one receipt per distinct item), one at a time."""
        yield from self._stream_jsonl(self._catalog, "catalog")

    def add_record(self, record: dict) -> None:
        """Append one witnessed run record to the durable run history (runs.jsonl)."""
        os.makedirs(self._root, exist_ok=True)
        with open(self._runs, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())

    def runs(self) -> Iterator[dict]:
        """Stream the run history: one witnessed RunRecord (as a dict) per gather session."""
        yield from self._stream_jsonl(self._runs, "runs")

    def load_item(self, row: dict) -> Item:
        """Reconstruct a full Item (body read from its object) from a catalog row. Note JSON's
        type limits: meta round-trips as JSON (tuples become lists); derived_from is restored as
        a tuple. The reconstructed item re-verifies, since the body hashes to its receipt."""
        text = self.read_text(row["sha256"], storage=row.get("storage"))
        prov = Provenance(
            source=row["source"], ref=row["ref"], method=row["method"],
            fetched_at=row["fetched_at"], sha256=row["sha256"],
            derived_from=tuple(row.get("derived_from") or []),
        )
        return Item(kind=row["kind"], id=row["id"], title=row["title"], text=text,
                    provenance=prov, meta=row.get("meta") or {})

    def _storage_for_sha(self, sha256: str) -> object | None:
        witnesses = [r.get("storage") for r in self.rows()
                     if r.get("sha256") == sha256 and r.get("storage") is not None]
        if not witnesses:
            return None
        first = witnesses[0]
        if any(w != first for w in witnesses[1:]):
            raise ValueError("catalog has conflicting storage witnesses for content hash")
        return first

    def _read_text_result(self, sha256: str, *, storage: object | None = None) -> StoredText:
        checked = _check_sha(sha256)
        if storage is None:
            storage = self._storage_for_sha(checked)
        with open(self._object_path(checked), "rb") as f:
            raw = f.read()
        return verify_stored_text(raw, checked, storage)

    def read_text(self, sha256: str, *, storage: object | None = None) -> str:
        result = self._read_text_result(sha256, storage=storage)
        if result.status != MATCH or result.text is None:
            raise ValueError("stored body does not match receipt")
        return result.text

    def read_observed_text(self, sha256: str) -> str:
        """Decode the current object bytes without verifying them against the receipt.

        This exists for availability probes, which must distinguish "object missing" from
        "object answered with different UTF-8 text". Integrity-sensitive callers should use
        ``read_text`` or ``verify``.
        """
        checked = _check_sha(sha256)
        with open(self._object_path(checked), "rb") as f:
            return f.read().decode("utf-8")

    def verify(self) -> list[dict]:
        """Re-hash every stored body against its receipt. Returns one row per catalog entry with a
        ``status`` of MATCH, MISSING, or CORRUPT. Reads bodies one at a time (never all at once)."""
        results = []
        for row in self.rows():
            rid = row.get("id", "")
            sha = row.get("sha256")
            if not isinstance(sha, str) or not sha:
                results.append({"id": rid, "sha256": sha or "", "status": CORRUPT})  # a row missing its
                continue                                                              # hash is corrupt, not a crash
            try:
                path = self._object_path(sha)
            except ValueError:
                results.append({"id": rid, "sha256": sha, "status": CORRUPT})
                continue
            checked: StoredText | None = None
            if not os.path.exists(path):
                status = MISSING
            else:
                with open(path, "rb") as f:
                    raw = f.read()
                checked = verify_stored_text(raw, sha, row.get("storage"))
                status = checked.status
            out = {"id": rid, "sha256": sha, "status": status}
            if checked is not None:
                out.update({
                    "storage_status": checked.storage_status,
                    "storage_witnessed": checked.storage_witnessed,
                    "object_sha256": checked.object_sha256,
                })
            results.append(out)
        return results

    def digest(self) -> Digest:
        """Fold the whole corpus catalog into one witnessed digest, from the rows alone. Equals a
        live ``digest(items)`` when the corpus holds exactly those distinct items."""
        return digest_of_receipts(list(self.rows()))

    def stats(self) -> dict:
        """A read-only summary of the catalog: item count, distinct bodies, and counts by source,
        kind, and method. Streams the catalog; reads no bodies."""
        by_source: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        by_method: dict[str, int] = {}
        shas: set[str] = set()
        items = 0
        for r in self.rows():
            items += 1
            shas.add(_field(r, "sha256"))
            for table, key in ((by_source, "source"), (by_kind, "kind"), (by_method, "method")):
                val = _field(r, key)
                table[val] = table.get(val, 0) + 1
        return {
            "items": items, "distinct_bodies": len(shas),
            "by_source": dict(sorted(by_source.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "by_method": dict(sorted(by_method.items())),
        }

    def orphan_objects(self) -> list[str]:
        """Object files (committed, not staging) on disk not referenced by any catalog row: the
        leftover body from a crash between writing a body and appending its row. Read-only. Reads
        the catalog to learn what is referenced, so a malformed catalog raises before anything is
        judged an orphan (it must not mistake a live object for a leftover). ``.tmp`` staging files
        are skipped on purpose: one may be an in-flight write from a concurrent ``add`` and is not
        prune's to touch."""
        referenced = {_field(r, "sha256") for r in self.rows()}
        orphans: list[str] = []
        if not os.path.isdir(self._objects):
            return orphans
        for shard in sorted(os.listdir(self._objects)):
            shard_dir = os.path.join(self._objects, shard)
            if not os.path.isdir(shard_dir):
                continue
            for name in sorted(os.listdir(shard_dir)):
                if name.endswith(".tmp"):
                    continue  # a write-staging file; never prune it (could be an in-flight add)
                if shard + name not in referenced:
                    orphans.append(os.path.join(shard_dir, name))
        return orphans

    def prune(self, *, apply: bool = False) -> dict:
        """Report orphan object files; with ``apply=True``, delete them. Returns
        ``{orphans, removed, removed_paths, applied}`` (``removed_paths`` is the list of files
        deleted, an audit trail for the destructive op). Default is report-only (fail-safe): nothing
        is deleted unless ``apply`` is set, and a malformed catalog aborts before any deletion.

        Run prune with NO concurrent writer to the corpus: it reads the catalog then deletes, so a
        body written by another process after that read would look unreferenced. Not atomic: if a
        delete raises mid-way, ``removed_paths`` (had it returned) would be partial, so a raise
        means some prefix of the orphans was removed.
        """
        orphans = self.orphan_objects()  # raises on a malformed catalog -> nothing removed
        removed_paths: list[str] = []
        if apply:
            if orphans and next(self.rows(), None) is None:
                # an empty/absent catalog with bodies present (a torn write) would mark EVERY body an
                # orphan; refuse rather than delete the lot. Restore or verify the catalog first.
                raise ValueError("catalog has no rows but objects exist; refusing to prune (verify the catalog)")
            for path in orphans:
                os.remove(path)
                removed_paths.append(path)
        return {"orphans": len(orphans), "removed": len(removed_paths),
                "removed_paths": removed_paths, "applied": apply}
