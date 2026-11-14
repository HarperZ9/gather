"""Read one CMMNS save: the Markdown sidecar (``daylight.sidecar/1``) and its optional JSON sidecar.

A Markdown sidecar starts with front matter between two ``---`` lines, one ``key: <JSON value>``
per line. The item's own text is the first run of ``>`` lines after the ``# `` heading. A
``<stem>.json`` file beside it holds a fuller record, and its values win when they are present.

Every file is untrusted data. Nothing in a sidecar is executed or followed; a bad value becomes a
problem string for the manifest and the rest of the file is still read.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

FORMAT = "daylight.sidecar/1"

_ID_PATTERNS = (
    (r"/status(?:es)?/(\d+)", 1), (r"/comments/([a-z0-9]+)", 1), (r"/post/([a-z0-9]+)", 1),
    (r"[?&]v=([\w-]{6,})", 1), (r"youtu\.be/([\w-]{6,})", 1), (r"/shorts/([\w-]{6,})", 1),
    (r"/(p|reel|reels|tv)/([\w-]+)", 2), (r"/video/(\d+)", 1),
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_URL_TAIL = ".,;:!?)]}'\""


@dataclass
class Sidecar:
    """One save, merged from the front matter, the body and the JSON sidecar."""

    path: str
    sha256: str
    meta: dict
    text: str = ""
    record: dict = field(default_factory=dict)
    body_links: list = field(default_factory=list)
    json_path: str = ""
    problems: list = field(default_factory=list)

    def pick(self, json_key: str, meta_key: str) -> str:
        """The JSON sidecar's string value, else the front matter's, else an empty string."""
        for value in (self.record.get(json_key), self.meta.get(meta_key)):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""


def decode(raw: bytes) -> str:
    """UTF-8 text with a BOM dropped, bad bytes replaced and every line ending as LF."""
    text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_text(text: str) -> str:
    """NFC, LF line endings, no trailing whitespace on any line."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.rstrip() for line in text.split("\n"))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def scrub(value):
    """A parsed JSON value with every string made safe to encode as UTF-8 (lone surrogates replaced)."""
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    return value


def split_front_matter(text: str) -> tuple[dict, str, list[str]] | None:
    """(front matter, body, problems), or None when the text has no closed front matter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    meta: dict = {}
    problems: list[str] = []
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or not key:
            problems.append("front matter line without a key")
            continue
        try:
            meta[key] = scrub(json.loads(value.strip()))
        except (ValueError, RecursionError):
            problems.append(f"front matter key {key}: value is not JSON")
            meta[key] = value.strip()
    return meta, "\n".join(lines[end + 1:]), problems


def body_text(body: str) -> str:
    """The first run of ``>`` lines after the ``# `` heading, before any later heading or label."""
    lines = body.split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if start is None:
        return ""
    run: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith(">"):
            run.append(line[2:] if line.startswith("> ") else line[1:])
        elif run:
            break
        elif line.startswith(("#", "- ")) or line.rstrip().endswith(":"):
            break
    return "\n".join(run)


def body_link_list(body: str) -> list[str]:
    """The addresses on the body's last ``- Links:`` line."""
    found: list[str] = []
    for line in body.split("\n"):
        if line.startswith("- Links:"):
            found = line[len("- Links:"):].split()
    return [link for link in found if _URL.fullmatch(link)]


def find_links(text: str) -> list[str]:
    return [m.group(0).rstrip(_URL_TAIL) for m in _URL.finditer(text)]


def load_json_record(raw: bytes) -> tuple[dict, str]:
    """(record, problem). The record is empty when the file is not a JSON object."""
    try:
        doc = scrub(json.loads(decode(raw)))
    except (ValueError, RecursionError):
        return {}, "JSON sidecar is not valid JSON"
    if not isinstance(doc, dict):
        return {}, "JSON sidecar is not an object"
    return doc, ""


def parse_sidecar(path: str, raw: bytes) -> Sidecar | None:
    """The save at ``path``, or None when the file is not a ``daylight.sidecar/1`` item."""
    parts = split_front_matter(decode(raw))
    if parts is None or parts[0].get("format") != FORMAT:
        return None
    meta, body, problems = parts
    return Sidecar(path=path, sha256=hashlib.sha256(raw).hexdigest(), meta=meta,
                   text=normalize_text(body_text(body)), body_links=body_link_list(body), problems=problems)


def attach_record(sc: Sidecar, record: dict) -> None:
    """Merge the JSON sidecar: its text replaces the body's when it is a non-empty string."""
    sc.record = record
    text = record.get("text")
    if isinstance(text, str) and text.strip():
        sc.text = normalize_text(text)


def str_list(value) -> list[str]:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def author_fields(sc: Sidecar) -> tuple[str, str]:
    """(author name, handle): the JSON sidecar's author object first, then the front matter."""
    author = sc.record.get("author")
    name, handle = _text(author), ""
    if isinstance(author, dict):
        name, handle = _text(author.get("name")), _text(author.get("handle"))
    return name or _text(sc.meta.get("author")), handle or _text(sc.meta.get("handle"))


def link_list(sc: Sidecar) -> list[str]:
    """Links in order of first appearance: the item text first, then the sidecar's own list."""
    listed = str_list(sc.record.get("links")) or sc.body_links
    seen: dict[str, None] = {}
    for link in find_links(sc.text) + listed:
        seen.setdefault(link, None)
    return list(seen)


def item_id(site: str, post: str, page: str, media: str, path: str) -> str:
    """``<site>:<post id>`` from the post address, else ``<site>:h-<16 hex>`` of an address or the path."""
    prefix = site or "unknown"
    for pattern, group in _ID_PATTERNS:
        m = re.search(pattern, post)
        if m:
            return f"{prefix}:{m.group(group)}"
    basis = post or page or media or path
    return f"{prefix}:h-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:16]}"
