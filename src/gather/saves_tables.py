"""Turn a folder of CMMNS saves into data tables by fixed rules.

``build_tables(root, out)`` walks ``root`` in sorted order, reads every ``daylight.sidecar/1``
Markdown sidecar with its optional JSON sidecar, and writes ``items``, ``entities`` and ``media``
as CSV and JSON Lines plus ``manifest.json`` (``gather.saves-tables/1``). The out folder is
skipped during the walk. No model call, no network call and no subprocess: the same folder gives
byte-identical files on every run, wherever the folder is and whatever its file times are.
"""

from __future__ import annotations

import os
import posixpath

from gather.media_probe import COLUMNS as PROBE_COLUMNS
from gather.media_probe import MEDIA_EXTENSIONS, probe
from gather.saves_entities import extract_entities
from gather.saves_lang import detect_language, sidecar_language
from gather.saves_sidecar import (
    Sidecar,
    attach_record,
    author_fields,
    content_hash,
    item_id,
    link_list,
    load_json_record,
    parse_sidecar,
    str_list,
)
from gather.saves_write import write_outputs

ITEM_COLUMNS = (
    "id", "site", "adapter", "kind", "author", "handle", "posted_time", "saved_time", "title", "text_length",
    "links", "link_list", "media_count", "media_kinds", "media_file", "language", "post_url", "page_url",
    "sidecar_path", "json_path", "thread_path", "file_paths", "missing_files", "content_hash", "sidecar_sha256")
ENTITY_COLUMNS = ("item_id", "sidecar_path", "type", "value", "normalized", "count")
MEDIA_COLUMNS = ("path", "item_id", "listed", *PROBE_COLUMNS)
NOT_LISTED = "not saved (no media file listed)"


class Folder:
    """The input folder: its sorted file list, byte reads, and the problems met on the way."""

    def __init__(self, root: str, out: str):
        self.root = root
        self.skip = os.path.normcase(os.path.realpath(out))
        self.problems: set[tuple[str, str]] = set()
        self.files: list[str] = []
        self._walk(root, "")
        self.names = set(self.files)

    def _walk(self, folder: str, rel: str) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as exc:
            self.problems.add((rel or ".", f"folder not read: {type(exc).__name__}"))
            return
        for entry in entries:
            child = f"{rel}/{entry.name}" if rel else entry.name
            if entry.is_dir(follow_symlinks=False):
                if os.path.normcase(os.path.realpath(entry.path)) != self.skip:
                    self._walk(entry.path, child)
            elif entry.is_file(follow_symlinks=False):
                self.files.append(child)

    def path(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def read(self, rel: str) -> bytes | None:
        try:
            with open(self.path(rel), "rb") as f:
                return f.read()
        except OSError as exc:
            self.problems.add((rel, f"file not read: {type(exc).__name__}"))
            return None

    def beside(self, sidecar: str, name: str) -> str | None:
        """The relative path of a file named by a sidecar, or None when the name leaves the folder."""
        name = name.replace("\\", "/")
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(sidecar), name))
        if name.startswith("/") or ":" in name or rel == ".." or rel.startswith("../"):
            self.problems.add((sidecar, "listed file name points outside the folder"))
            return None
        return rel


def load_sidecars(folder: Folder) -> tuple[list[Sidecar], int]:
    """(items, skipped Markdown count). A JSON sidecar is merged when one sits beside the item."""
    items: list[Sidecar] = []
    skipped = 0
    for rel in folder.files:
        if not rel.lower().endswith(".md"):
            continue
        raw = folder.read(rel)
        sc = parse_sidecar(rel, raw) if raw is not None else None
        if sc is None:
            skipped += 1
            if raw is not None and raw.lstrip(b"\xef\xbb\xbf").startswith(b"---") and b"daylight.sidecar/" in raw:
                folder.problems.add((rel, "sidecar front matter is not closed or names another format"))
            continue
        json_rel = rel[:-3] + ".json"
        json_raw = folder.read(json_rel) if json_rel in folder.names else None
        if json_raw is not None:
            record, problem = load_json_record(json_raw)
            attach_record(sc, record)
            sc.problems.extend([problem] if problem else [])
            sc.json_path = json_rel
        folder.problems.update((rel, p) for p in sc.problems)
        items.append(sc)
    return items, skipped


def base_fields(sc: Sidecar) -> dict:
    """The columns that come straight from the sidecars, before any file on disk is looked at."""
    site = sc.pick("site", "site")
    author, handle = author_fields(sc)
    post, page = sc.pick("postUrl", "post"), sc.pick("pageUrl", "page")
    title = sc.pick("title", "title")
    page_meta = sc.record.get("page")
    page_meta = page_meta if isinstance(page_meta, dict) else {}
    language = (sidecar_language(page_meta.get("lang")) or sidecar_language(sc.record.get("lang"))
                or sidecar_language(sc.meta.get("lang")) or detect_language(f"{title}\n{sc.text}"))
    links = link_list(sc)
    return {
        "id": item_id(site, post, page, sc.pick("mediaUrl", "media"), sc.path), "site": site,
        "adapter": sc.pick("adapter", "adapter") or f"legacy:{site or 'unknown'}", "kind": sc.pick("kind", "kind"),
        "author": author, "handle": handle, "posted_time": sc.pick("postedAt", "posted"),
        "saved_time": sc.pick("savedAt", "saved"), "title": title, "text_length": len(sc.text),
        "links": len(links), "link_list": " ".join(links), "language": language, "post_url": post, "page_url": page,
        "sidecar_path": sc.path, "json_path": sc.json_path,
        "content_hash": content_hash(sc.text), "sidecar_sha256": sc.sha256,
    }


def listed_files(folder: Folder, sc: Sidecar) -> tuple[list[str], int]:
    """(listed files that exist, count of listed files that do not)."""
    names = str_list(sc.record.get("files")) or str_list(sc.meta.get("files"))
    existing: dict[str, None] = {}
    missing = 0
    for name in names:
        rel = folder.beside(sc.path, name)
        if rel is not None and rel in folder.names:
            existing.setdefault(rel, None)
        else:
            missing += 1
    return list(existing), missing


def thread_path(folder: Folder, sc: Sidecar) -> str:
    named = sc.meta.get("thread_file")
    rel = folder.beside(sc.path, named) if isinstance(named, str) and named else None
    if rel is not None and rel in folder.names:
        return rel
    default = sc.path[:-3] + ".thread.json"
    return default if default in folder.names else ""


def media_row(folder: Folder, rel: str, owner: str, listed: bool, with_hash: bool) -> dict:
    row = {"path": rel, "item_id": owner, "listed": listed}
    try:
        fields, note = probe(folder.path(rel), with_hash)
    except OSError as exc:
        fields, note = dict.fromkeys(PROBE_COLUMNS), f"media file not read: {type(exc).__name__}"
    if note:
        folder.problems.add((rel, note))
    row.update(fields)
    return row


def build_rows(folder: Folder, sidecars: list[Sidecar], with_hash: bool) -> tuple[list[dict], list[dict], list[dict]]:
    """(item rows, entity rows, media rows), each in its documented order."""
    bases = sorted(((base_fields(sc), sc) for sc in sidecars), key=lambda p: (p[0]["site"], p[0]["id"], p[1].path))
    media: dict[str, dict] = {}
    items, entities = [], []
    for base, sc in bases:
        existing, missing = listed_files(folder, sc)
        for rel in existing:
            if rel not in media:
                media[rel] = media_row(folder, rel, base["id"], True, with_hash)
        kinds = sorted({media[rel]["kind"] or "other" for rel in existing})
        saved = "saved" if existing else (NOT_LISTED if base["kind"] == "media" else "")
        base.update(media_count=len(existing), media_kinds="+".join(kinds), missing_files=missing,
                    media_file=sc.pick("mediaFile", "media_file") or saved, file_paths=";".join(existing),
                    thread_path=thread_path(folder, sc))
        items.append(base)
        text = f"{base['title']}\n{sc.text}" if base["title"] else sc.text
        entities += [{"item_id": base["id"], "sidecar_path": sc.path, **row} for row in extract_entities(text)]
    for rel in folder.files:
        if rel not in media and rel.rsplit(".", 1)[-1].lower() in MEDIA_EXTENSIONS:
            media[rel] = media_row(folder, rel, "", False, with_hash)
    entities.sort(key=lambda r: (r["item_id"], r["sidecar_path"], r["type"], r["value"], r["normalized"]))
    return items, entities, [media[rel] for rel in sorted(media)]


def build_tables(root: str, out: str, media_hash: bool = True) -> dict:
    """Write the tables for ``root`` into ``out`` and return the manifest.

    Raises ValueError when ``root`` is not a folder or ``out`` is the input folder itself.
    """
    if not os.path.isdir(root):
        raise ValueError("the input is not a folder")
    if os.path.normcase(os.path.realpath(out)) == os.path.normcase(os.path.realpath(root)):
        raise ValueError("--out is the input folder; give a folder inside or outside it")
    folder = Folder(root, out)
    sidecars, skipped = load_sidecars(folder)
    items, entities, media = build_rows(folder, sidecars, media_hash)
    tables = (("items", ITEM_COLUMNS, items), ("entities", ENTITY_COLUMNS, entities), ("media", MEDIA_COLUMNS, media))
    problems = [{"path": path, "problem": problem} for path, problem in sorted(folder.problems)]
    return write_outputs(out, tables, {"input_items": len(items), "skipped_markdown": skipped, "problems": problems})
