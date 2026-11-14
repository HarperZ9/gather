"""Synthetic saves for the ``gather saves`` tests: sidecars with invented names and tiny media
files built with ``struct``. Nothing here is a real post."""

import json
import struct

ANA = "ana_2026-11-14_seaford-argues_2121395628576284802"
ANA_TEXT = "@bo Seaford argues that the spread of coinage helped make abstract thinking possible https://t.co/SO2V0fz6h0"
ANA_MD = f"""---
format: "daylight.sidecar/1"
files: ["{ANA}.jpg"]
kind: "media"
site: "x"
handle: "ana"
author: "Ana Example"
posted: "2026-11-14T00:11:46.000Z"
saved: "2026-11-14T00:44:34.189Z"
post: "https://x.com/ana/status/2121395628576284802"
media: "https://pbs.twimg.com/media/HXC152HW4AArb6j?format=jpg&name=orig"
engagement: {{"replies":0,"reposts":0,"quotes":0,"likes":0,"bookmarks":0,"views":219,"at":"2026-11-14T00:44:34.189Z"}}
thread_file: "{ANA}.thread.json"
comments_captured: 0
---

# Ana Example @ana

> {ANA_TEXT}

Replying to @bo (https://x.com/bo/status/2121265316563124432):

> quoted parent text with #NotMine and https://example.com/parent

## Comments

No comments: the site counted none on this post.

- File: {ANA}.jpg
- Post: https://x.com/ana/status/2121395628576284802
- Links: https://t.co/SO2V0fz6h0

Saved by CMMNS from what the page showed.
"""
NOTE_TEXT = "Reading arXiv:2301.12345 on 5 March 2024.\nIt cost $1,200 #Money"
NOTE_MD = ("\ufeff---\nformat: \"daylight.sidecar/1\"\nfiles: []\nkind: \"text\"\nsite: \"x\"\nhandle: \"bo\"\n"
           "post: \"https://x.com/bo/status/2121265316563124432\"\nsaved: \"2026-11-14T01:00:00.000Z\"\n---\n\n"
           "# Bo Example @bo\n\n> Reading arXiv:2301.12345 on 5 March 2024.   \n> It cost $1,200 #Money\n").replace("\n", "\r\n")
AGAIN_MD = ('---\nformat: "daylight.sidecar/1"\nfiles: []\nkind: "text"\nsite: "x"\nhandle: "ana"\n'
            'post: "https://x.com/ana/status/2121395628576284802"\n---\n\n# Ana Example @ana\n\n> saved a second time\n')
YOUTUBE_MD = ('---\nformat: "daylight.sidecar/1"\nfiles: ["thumb.jpg"]\nkind: "media"\nsite: "youtube"\n'
              'handle: "chan"\npost: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"\nengagement: {"likes":\n---\n\n'
              "# Chan\n\n## Comments\n\n> a comment, not the item text\n")
PAGE_MD = ('---\nformat: "daylight.sidecar/1"\nfiles: ["page.png"]\nkind: "media"\nsite: "example.org"\n'
           'adapter: "generic"\npage: "https://example.org/front-matter-page"\n---\n\n# A page\n\n> body text that the JSON replaces\n')
PAGE_TEXT = "El informe dice que los datos son muy claros y no hay dudas.\nVer https://doi.org/10.5555/Abc.1 para más."
PAGE_JSON = {
    "text": PAGE_TEXT, "title": "Informe económico 2026", "author": {"name": "Cy Example", "handle": "cy"},
    "pageUrl": "https://example.org/informe", "savedAt": "2026-11-13T09:00:00.000Z",
    "links": ["https://example.org/more", "https://doi.org/10.5555/Abc.1"], "adapter": "generic",
    "mediaFile": "saved", "page": {"lang": "es-MX", "canonical": "https://example.org/informe"},
    "files": ["page.png"], "items": [{"kind": "image", "url": "https://example.org/a.png", "alt": ""}],
}
BROKEN_MD = '---\nformat: "daylight.sidecar/1"\nfiles: []\n\n# never closed\n'
PLAIN_MD = "# Notes\n\nNot a sidecar.\n"


def png_bytes(width=7, height=5):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"\x08\x02\x00\x00\x00" + b"\0" * 4


def jpeg_bytes(width=4, height=3):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\0" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def gif_bytes(width=9, height=8):
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\0" * 3 + b";"


def wav_bytes(rate=8000, channels=2, data_bytes=16000):
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", data_bytes) + b"\0" * data_bytes
    return b"RIFF" + struct.pack("<I", len(body)) + body


def box(kind, payload, wide=False):
    if wide:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _tkhd(width, height):
    return box(b"tkhd", b"\0" * 76 + struct.pack(">II", width << 16, height << 16))


def _mdhd(timescale, duration):
    return box(b"mdhd", struct.pack(">IIIII", 0, 0, 0, timescale, duration) + b"\0" * 4)


def _hdlr(kind):
    return box(b"hdlr", b"\0" * 8 + kind + b"\0" * 13)


def mp4_bytes(width=320, height=240, rate=44100, channels=2):
    """ftyp, a 64-bit-size mdat, then moov at the end with one video and one audio track."""
    entry = struct.pack(">I4s6xH", 36, b"mp4a", 1) + struct.pack(">HHIHHHHI", 0, 0, 0, channels, 16, 0, 0, rate << 16)
    stsd = box(b"stsd", struct.pack(">II", 0, 1) + entry)
    video = box(b"trak", _tkhd(width, height) + box(b"mdia", _mdhd(30000, 75000) + _hdlr(b"vide")))
    audio = box(b"trak", _tkhd(0, 0) + box(b"mdia", _mdhd(rate, rate * 2) + _hdlr(b"soun")
                                           + box(b"minf", box(b"stbl", stsd))))
    mvhd = box(b"mvhd", struct.pack(">IIIII", 0, 0, 0, 1000, 2500) + b"\0" * 80)
    return (box(b"ftyp", b"isom\0\0\x02\0isomiso2") + box(b"mdat", b"\x01" * 64, wide=True)
            + box(b"moov", mvhd + video + audio))


def make_tree(root):
    """Write the fixture tree under ``root`` and return ``root``."""
    files = {
        f"x/{ANA}.md": ANA_MD, f"x/{ANA}.jpg": jpeg_bytes(), f"x/{ANA}.thread.json": json.dumps({"comments": []}),
        "x/note.md": NOTE_MD, "x/again.md": AGAIN_MD, "youtube/ref.md": YOUTUBE_MD,
        "web/page.md": PAGE_MD, "web/page.json": json.dumps(PAGE_JSON, ensure_ascii=False), "web/page.png": png_bytes(),
        "web/broken.md": BROKEN_MD, "web/loose.gif": gif_bytes(), "notes/readme.md": PLAIN_MD,
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return root
