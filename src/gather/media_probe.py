"""Probe one local media file with the standard library: container, size, and the header fields.

``probe(path)`` names the container from the file's first bytes, never from its extension, and
reads picture size, duration, sample rate and channels from the container's own headers. A field
that cannot be read is ``None`` (an empty cell in the tables); nothing is guessed. The file is
hashed by streaming, and large media is never read into memory. No subprocess and no network.
"""

from __future__ import annotations

import hashlib
import os
import struct

from gather.media_probe_audio import flac, id3_size, mp3, mp3_header, ogg, wav
from gather.media_probe_bmff import PartialRead, bmff, brand
from gather.media_probe_ebml import ebml
from gather.media_probe_image import gif, jpeg, png, webp

FIELDS = ("width", "height", "duration_seconds", "sample_rate", "channels")
COLUMNS = ("kind", "container", "bytes", *FIELDS, "sha256")
MEDIA_EXTENSIONS = {
    "jpg": "image", "jpeg": "image", "png": "image", "gif": "image", "webp": "image",
    "mp4": "video", "m4v": "video", "mov": "video", "webm": "video", "mkv": "video",
    "mp3": "audio", "m4a": "audio", "wav": "audio", "ogg": "audio", "opus": "audio", "flac": "audio",
}
_KINDS = {"jpeg": "image", "png": "image", "gif": "image", "webp": "image", "mp4": "video", "mov": "video",
          "webm": "video", "matroska": "video", "wav": "audio", "mp3": "audio", "ogg": "audio", "flac": "audio",
          "m4a": "audio"}
_READERS = {"jpeg": jpeg, "png": png, "gif": gif, "webp": webp, "mp4": bmff, "mov": bmff, "m4a": bmff,
            "webm": ebml, "matroska": ebml, "wav": wav, "mp3": mp3, "ogg": ogg, "flac": flac}
_BARE_BOXES = (b"moov", b"mdat", b"free", b"wide", b"skip")
_CHUNK = 1 << 20


def sniff(head: bytes) -> str:
    """The container named by a file's first bytes, or ``unknown``."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] in (b"WEBP", b"WAVE"):
        return "webp" if head[8:12] == b"WEBP" else "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm" if b"webm" in head[:64] else "matroska"
    if head[4:8] == b"ftyp":
        return brand(head)
    if head[4:8] in _BARE_BOXES:
        return "mov"
    if head[:3] == b"ID3" or mp3_header(head[:4]) is not None:
        return "mp3"
    return "unknown"


def _sniff_file(f) -> str:
    head = f.read(64)
    container = sniff(head)
    if container == "mp3" and head[:3] == b"ID3":
        f.seek(id3_size(head))
        if f.read(4) == b"fLaC":
            return "unknown"  # a FLAC stream behind an ID3 tag is not read here
    return container


def media_kind(container: str, fields: dict, extension: str) -> str:
    """image, video, audio or other: from the container, then the extension when it is unknown."""
    kind = _KINDS.get(container) or MEDIA_EXTENSIONS.get(extension.lower().lstrip("."), "other")
    if container in ("mp4", "mov", "webm", "matroska") and not fields.get("width") and fields.get("sample_rate"):
        return "audio"
    return kind


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def read_fields(f, container: str, size: int) -> tuple[dict, str]:
    """(fields, note). The note says why fields are missing when the headers could not be read."""
    reader = _READERS.get(container)
    if reader is None:
        return {}, ""
    note = f"{container} headers could not be read in full"
    try:
        return reader(f, size), ""
    except PartialRead as exc:
        return exc.fields, note
    except (struct.error, ValueError, IndexError):
        return {}, note


def probe(path: str, with_hash: bool = True) -> tuple[dict, str]:
    """(row, note) for one file. Raises OSError when the file cannot be opened or read."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        container = _sniff_file(f)
        fields, note = read_fields(f, container, size)
    row = {"kind": media_kind(container, fields, os.path.splitext(path)[1]), "container": container, "bytes": size}
    row.update({name: fields.get(name) or None for name in FIELDS})
    row["sha256"] = sha256_file(path) if with_hash else None
    return row, note
