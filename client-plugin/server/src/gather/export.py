"""Uniform JSON / JSONL export for gather's receipts.

Every receipt in the engine (extraction, fetch, crawl ledger, schema record,
render result) serializes the same way, so a downstream tool, a sibling flagship,
or a reviewer gets one predictable shape. Objects that publish ``as_dict`` use it;
plain dataclasses fall back to a recursive field dump. Pure.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


def to_dict(obj, _seen=None):
    """Best-effort plain-data view: ``as_dict()`` if present, else recursive
    dataclass/dict/list conversion, else the value itself. Detects reference
    cycles and raises ``ValueError`` (matching json.dumps) rather than overflowing
    the stack; a value referenced twice without a cycle still serializes."""
    as_dict_fn = getattr(obj, "as_dict", None)
    if callable(as_dict_fn):
        return as_dict_fn()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (list, tuple, dict)):
        if _seen is None:
            _seen = set()
        oid = id(obj)
        if oid in _seen:
            raise ValueError("Circular reference detected")
        _seen.add(oid)
        try:
            if isinstance(obj, dict):
                return {k: to_dict(v, _seen) for k, v in obj.items()}
            return [to_dict(o, _seen) for o in obj]
        finally:
            _seen.discard(oid)
    return obj


def to_json(obj, *, indent: int = 2) -> str:
    # default=str keeps export total on a non-serializable leaf (datetime, Path, ...).
    return json.dumps(to_dict(obj), indent=indent, sort_keys=True, ensure_ascii=False, default=str)


def to_jsonl(items) -> str:
    return "\n".join(
        json.dumps(to_dict(i), sort_keys=True, ensure_ascii=False, default=str) for i in items
    )


def write_json(path, obj, *, indent: int = 2) -> None:
    Path(path).write_text(to_json(obj, indent=indent) + "\n", encoding="utf-8")


def write_jsonl(path, items) -> None:
    Path(path).write_text(to_jsonl(items) + "\n", encoding="utf-8")
