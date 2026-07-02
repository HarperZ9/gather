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


def to_dict(obj):
    """Best-effort plain-data view: ``as_dict()`` if present, else recursive
    dataclass/dict/list conversion, else the value itself."""
    as_dict_fn = getattr(obj, "as_dict", None)
    if callable(as_dict_fn):
        return as_dict_fn()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [to_dict(o) for o in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def to_json(obj, *, indent: int = 2) -> str:
    return json.dumps(to_dict(obj), indent=indent, sort_keys=True, ensure_ascii=False)


def to_jsonl(items) -> str:
    return "\n".join(
        json.dumps(to_dict(i), sort_keys=True, ensure_ascii=False) for i in items
    )


def write_json(path, obj, *, indent: int = 2) -> None:
    Path(path).write_text(to_json(obj, indent=indent) + "\n", encoding="utf-8")


def write_jsonl(path, items) -> None:
    Path(path).write_text(to_jsonl(items) + "\n", encoding="utf-8")
