"""Structural handlers for plain text, JSON and the CMMNS Markdown sidecar.

All three keep the exact bytes: a byte order mark is its own node, every line keeps its own line
ending, and JSON whitespace is a token like any other. Text must be valid UTF-8 with no NUL byte
and no larger than the text limit; anything else is left to the raw handler.
"""

from __future__ import annotations

import json
import re

from gather.decompose_tree import Maker

BOM = b"\xef\xbb\xbf"
SIDECAR_FORMAT = b'format: "daylight.sidecar/1"'
_LINE = re.compile(rb"[^\r\n]*(?:\r\n|\n|\r|$)")
_ENDINGS = {b"\r\n": "crlf", b"\n": "lf", b"\r": "cr"}
_TOKEN = re.compile(
    rb'(?P<whitespace>[ \t\n\r]+)|(?P<punctuation>[{}\[\]:,])|(?P<string>"(?:[^"\\\x00-\x1f]|\\.)*")'
    rb"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<literal>true|false|null)")


def load_text(m: Maker, ctx) -> tuple[bytes, int]:
    """(all bytes, length of the byte order mark). Raises ValueError when the source is not text."""
    if m.src.size > ctx.limits.max_text_bytes:
        raise ValueError("larger than the text limit")
    data = m.src.read(0, m.src.size)
    if b"\x00" in data:
        raise ValueError("holds a NUL byte")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not valid UTF-8") from None
    return data, len(BOM) if data.startswith(BOM) else 0


def _ending(line: bytes) -> str:
    return next((name for end, name in _ENDINGS.items() if line.endswith(end)), "none")


def line_nodes(m: Maker, data: bytes, start: int, end: int, limit: int) -> list[dict]:
    """One ``line`` node per line in ``start..end``; past ``limit`` lines the rest is one ``raw`` node."""
    nodes: list[dict] = []
    pos = start
    while pos < end:
        if len(nodes) >= limit:
            nodes.append(m.leaf("raw", pos, end - pos, note="line limit reached"))
            break
        stop = min(_LINE.match(data, pos).end(), end)  # type: ignore[union-attr]
        nodes.append(m.leaf("line", pos, stop - pos, ending=_ending(data[pos:stop])))
        pos = stop
    return nodes


def _with_bom(m: Maker, bom: int, parts: list[dict]) -> list[dict]:
    return ([m.leaf("byte-order-mark", 0, bom)] if bom else []) + parts


def build_text(m: Maker, ctx, depth: int) -> dict:
    data, bom = load_text(m, ctx)
    lines = line_nodes(m, data, bom, len(data), ctx.limits.max_units)
    endings = sorted({n["params"]["ending"] for n in lines if n["kind"] == "line"})
    return m.cover("text", 0, len(data), _with_bom(m, bom, lines), lines=len(lines), endings=endings)


def build_json(m: Maker, ctx, depth: int) -> dict:
    """JSON as a flat run of tokens, each with its bracket depth."""
    data, bom = load_text(m, ctx)
    if data[bom:].lstrip(b" \t\r\n")[:1] not in (b"{", b"["):
        raise ValueError("does not start with an object or an array")
    tokens: list[dict] = []
    pos, level = bom, 0
    while pos < len(data):
        match = _TOKEN.match(data, pos)
        if match is None:
            raise ValueError("a byte that is not a JSON token")
        if len(tokens) >= ctx.limits.max_units:
            tokens.append(m.leaf("raw", pos, len(data) - pos, note="token limit reached"))
            break
        text = match.group(0)
        level -= text in (b"}", b"]")
        tokens.append(m.leaf(f"json-{match.lastgroup}", pos, len(text), depth=level))
        level += text in (b"{", b"[")
        pos = match.end()
    try:
        json.loads(data[bom:])
        valid = True
    except (ValueError, RecursionError):
        valid = False
    return m.cover("json", 0, len(data), _with_bom(m, bom, tokens), tokens=len(tokens), valid=valid)


def _line_class(line: bytes) -> str:
    text = line.strip()
    if not text:
        return "blank"
    if text.startswith(b"#"):
        return "heading"
    if text.startswith(b">"):
        return "quote"
    return "list" if text.startswith(b"- ") else "paragraph"


def _front_matter(m: Maker, data: bytes, lines: list[dict]) -> dict:
    for node in lines[1:-1]:
        key, sep, value = data[node["_start"]:node["_start"] + node["length"]].partition(b":")
        node["kind"] = "front-matter-line"
        try:
            json.loads(value)
            ok = bool(sep)
        except (ValueError, RecursionError):
            ok = False
        node["params"].update(key=key.decode("utf-8", "replace").strip(), value_is_json=ok)
    lines[0]["kind"], lines[-1]["kind"] = "front-matter-open", "front-matter-close"
    return m.group("front-matter", lines, lines=len(lines) - 2)


def _blocks(m: Maker, data: bytes, lines: list[dict]) -> list[dict]:
    """Runs of lines of one class (heading, quote, list, paragraph, blank) as block nodes."""
    blocks: list[dict] = []
    run: list[dict] = []
    current = ""
    for node in lines:
        kind = "raw" if node["kind"] == "raw" else _line_class(data[node["_start"]:node["_start"] + node["length"]])
        if run and kind != current:
            blocks.append(m.group(f"block-{current}", run, lines=len(run)))
            run = []
        current = kind
        run.append(node)
    if run:
        blocks.append(m.group(f"block-{current}", run, lines=len(run)))
    return blocks


def build_sidecar(m: Maker, ctx, depth: int) -> dict:
    """A ``daylight.sidecar/1`` Markdown file: front matter lines, then body blocks of lines."""
    data, bom = load_text(m, ctx)
    lines = line_nodes(m, data, bom, len(data), ctx.limits.max_units)
    texts = [data[n["_start"]:n["_start"] + n["length"]].strip() for n in lines]
    if not texts or texts[0] != b"---" or lines[-1]["kind"] == "raw":
        raise ValueError("no front matter")
    close = next((i for i in range(1, len(texts)) if texts[i] == b"---"), None)
    if close is None or SIDECAR_FORMAT not in texts[1:close]:
        raise ValueError("front matter is not closed or names another format")
    parts = [_front_matter(m, data, lines[:close + 1])]
    body = _blocks(m, data, lines[close + 1:])
    if body:
        parts.append(m.group("body", body, blocks=len(body)))
    return m.cover("cmmns-sidecar", 0, len(data), _with_bom(m, bom, parts), format="daylight.sidecar/1")
