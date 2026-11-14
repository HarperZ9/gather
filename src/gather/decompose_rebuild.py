"""Rebuild a file from its decompose tree, and verify the tree on the way.

``rebuild(tree_dir, out_file)`` writes the leaves in order and checks every node: its length,
its SHA-256, and that each child starts where the one before it ended. The report lists each
node that fails, by its path in the tree, and compares the result with the hash of the original
file recorded in ``tree.json``. With ``out_file=None`` it only verifies. Derived trees (decoded
copies) are verified too and never written. ``tree.json`` is read as untrusted data: a blob name
must be 64 hex digits, so it cannot point outside ``parts/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from gather.decompose_tree import TREE_FORMAT

_BLOB = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1 << 20


class _Null:
    def write(self, data: bytes) -> None:
        return None


class _Walk:
    """One pass over a tree: writes leaf bytes to a sink and records each node that fails a check."""

    def __init__(self, tree_dir: str, sink):
        self.parts = os.path.join(tree_dir, "parts")
        self.sink = sink
        self.hashers: list = []
        self.problems: list[dict] = []

    def _flag(self, path: str, node: dict, problem: str) -> None:
        self.problems.append({"node": path, "kind": str(node.get("kind")), "problem": problem})

    def _leaf(self, node: dict, path: str):
        if isinstance(node.get("hex"), str):
            try:
                yield bytes.fromhex(node["hex"])
            except ValueError:
                self._flag(path, node, "hex is not valid")
            return
        name = node.get("blob")
        if not isinstance(name, str) or not _BLOB.fullmatch(name):
            self._flag(path, node, "leaf has no bytes")
            return
        try:
            with open(os.path.join(self.parts, name), "rb") as f:
                while data := f.read(_CHUNK):
                    yield data
        except OSError:
            self._flag(path, node, "blob is missing")

    def emit(self, node: dict, path: str) -> int:
        """Write one node's bytes; return how many were written."""
        own = hashlib.sha256()
        self.hashers.append(own)
        written = 0
        if isinstance(node.get("children"), list):
            for i, child in enumerate(node["children"]):
                if child.get("offset") != written:
                    self._flag(f"{path}/{i}", child, "offset is not where the node before it ended")
                written += self.emit(child, f"{path}/{i}")
        else:
            for data in self._leaf(node, path):
                for hasher in self.hashers:
                    hasher.update(data)
                self.sink.write(data)
                written += len(data)
        self.hashers.pop()
        if written != node.get("length"):
            self._flag(path, node, "length differs")
        elif own.hexdigest() != node.get("sha256"):
            self._flag(path, node, "sha256 differs")
        derived = node.get("derived")
        if isinstance(derived, dict) and isinstance(derived.get("root"), dict):
            saved, self.sink, self.hashers = (self.sink, self.hashers), _Null(), []
            self.emit(derived["root"], f"{path}/derived")
            self.sink, self.hashers = saved
        return written


def load_tree(tree_dir: str) -> dict:
    """``tree.json`` as a dict. Raises ValueError when it is not a decompose tree."""
    try:
        with open(os.path.join(tree_dir, "tree.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError(f"tree.json cannot be read: {type(exc).__name__}") from None
    if not isinstance(doc, dict) or doc.get("format") != TREE_FORMAT or not isinstance(doc.get("root"), dict):
        raise ValueError("tree.json is not a gather.decompose-tree/1 record")
    return doc


def _pick(doc: dict, companion: str | None) -> dict:
    if companion is None:
        return {"root": doc["root"], "sha256": (doc.get("source") or {}).get("sha256")}
    for other in doc.get("companions") or []:
        if isinstance(other, dict) and other.get("name") == companion and isinstance(other.get("root"), dict):
            return other
    raise ValueError("the tree holds no companion with that name")


def rebuild(tree_dir: str, out_file: str | None, companion: str | None = None) -> dict:
    """Rebuild (or only verify) the file or one companion; return the report.

    Raises ValueError when the tree cannot be read and OSError when the output cannot be written.
    """
    target = _pick(load_tree(tree_dir), companion)
    digest = hashlib.sha256()
    sink = open(out_file, "wb") if out_file else _Null()
    walk = _Walk(tree_dir, sink)
    walk.hashers.append(digest)
    try:
        written = walk.emit(target["root"], "root")
    except (RecursionError, TypeError, AttributeError):
        raise ValueError("tree.json is not a well formed tree") from None
    finally:
        if out_file:
            sink.close()  # type: ignore[union-attr]
    match = digest.hexdigest() == target.get("sha256")
    if not match:
        walk.problems.append({"node": "root", "kind": "file", "problem": "rebuilt bytes differ from the original sha256"})
    return {"ok": match and not walk.problems, "bytes": written, "sha256": digest.hexdigest(),
            "expected_sha256": target.get("sha256"), "problems": walk.problems}
