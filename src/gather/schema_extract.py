"""Structured extraction: a schema of selectors to a JSON record, with every
field bound to its source node and hash, plus a hallucination-REJECT check.

Two capabilities, one accountable:

  - extract_schema(html, schema): deterministic, selector-driven extraction (the
    firecrawl `extract` shape) where each field value is lifted from a node and
    bound to that node's path and content hash. It cannot invent a value: every
    field came from the page, and verify() re-derives it.

  - verify_record(html, record): given a record proposed by anything (an LLM, a
    remote API, a human), confirm each field value is actually GROUNDED in the
    fetched content. Any value not present is REJECTED. This is the check that
    turns firecrawl-style LLM extraction from "trust the model" into "prove it
    against the source", which none of the competitors do.

Pure and deterministic. Composes with [dom.py]. The ``method`` is a direct read,
never inference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from gather.dom import norm, parse_dom, select
from gather.item import content_hash


@dataclass(frozen=True, slots=True)
class Field:
    """One field's extraction rule. ``attr=None`` reads the node's text; a regex
    narrows the source to its first group (or whole match). ``many`` collects all
    matches into a list."""

    selector: str
    attr: str | None = None
    regex: str | None = None
    many: bool = False
    required: bool = True


@dataclass(frozen=True, slots=True)
class Hit:
    value: str
    path: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class FieldValue:
    name: str
    hits: tuple[Hit, ...]
    attr: str | None
    many: bool
    required: bool

    @property
    def value(self):
        vals = [h.value for h in self.hits]
        return vals if self.many else (vals[0] if vals else None)

    @property
    def status(self) -> str:
        return "extracted" if self.hits else "missing"


def _apply_regex(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    if not m:
        return None
    return m.group(1) if m.groups() else m.group(0)


def _extract_field(root, spec: Field) -> list[Hit]:
    hits: list[Hit] = []
    for node in select(root, spec.selector):
        source = norm(node.attrs.get(spec.attr, "") if spec.attr else node.text_content())
        value = source
        if spec.regex:
            got = _apply_regex(source, spec.regex)
            if got is None:
                continue
            value = got
        if not value:
            continue
        hits.append(Hit(value, node.path, content_hash(source)))
        if not spec.many:
            break
    return hits


@dataclass(frozen=True, slots=True)
class SchemaExtraction:
    url: str
    method: str
    fetched_at: float
    content_sha256: str
    fields: tuple[FieldValue, ...]

    def record(self) -> dict:
        return {f.name: f.value for f in self.fields}

    def missing_required(self) -> list[str]:
        return [f.name for f in self.fields if f.required and not f.hits]

    def verify(self, html: str) -> bool:
        """Re-derive every field from ``html`` and confirm each value still sits
        at its source node with a matching hash and is grounded in that source."""
        if content_hash(html) != self.content_sha256:
            return False
        by_path = {n.path: n for n in parse_dom(html).walk()}
        for f in self.fields:
            for h in f.hits:
                node = by_path.get(h.path)
                if node is None:
                    return False
                source = norm(node.attrs.get(f.attr, "") if f.attr else node.text_content())
                if content_hash(source) != h.source_sha256:
                    return False
                if norm(h.value).lower() not in source.lower():
                    return False
        return True


def extract_schema(
    html: str, schema: dict[str, Field], url: str, *, fetched_at: float,
    method: str = "schema-extract",
) -> SchemaExtraction:
    """Extract a record from ``html`` per ``schema``; every field is bound to its
    source node path and hash. Pure."""
    root = parse_dom(html)
    fields = tuple(
        FieldValue(name, tuple(_extract_field(root, spec)), spec.attr, spec.many, spec.required)
        for name, spec in schema.items()
    )
    return SchemaExtraction(url, method, float(fetched_at), content_hash(html), fields)


# ─── hallucination REJECT ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FieldVerdict:
    name: str
    value: str
    grounded: bool


@dataclass(frozen=True, slots=True)
class RecordVerdict:
    verdicts: tuple[FieldVerdict, ...]
    content_sha256: str

    @property
    def rejected(self) -> tuple[FieldVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.grounded)

    @property
    def ok(self) -> bool:
        return not self.rejected


def _haystack(root) -> str:
    parts = [root.text_content()]
    for n in root.walk():
        parts.extend(n.attrs.values())
    return norm(" ".join(parts)).lower()


def verify_record(html: str, record: dict) -> RecordVerdict:
    """Check every value in ``record`` is grounded in the fetched content. A value
    that appears nowhere on the page is REJECTED (a fabricated/hallucinated
    field). Pure."""
    hay = _haystack(parse_dom(html))
    verdicts: list[FieldVerdict] = []
    for name, value in record.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            token = norm(str(v)).lower()
            verdicts.append(FieldVerdict(name, str(v), bool(token) and token in hay))
    return RecordVerdict(tuple(verdicts), content_hash(html))
