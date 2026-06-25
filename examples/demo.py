"""Gather: a tour of the research-intake organ (offline, no install, nothing downloaded).

Parses an already-harvested video (a yt-dlp info.json plus its .vtt captions) into items,
each with a provenance receipt, scope-filters them to the work, and folds them into a
witnessed digest. Then it tampers with one item and shows the receipt catch it.

Run:  python examples/demo.py
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from gather.digest import digest, verify_digest
from gather.scope import filter_scope
from gather.video import parse_video

INFO = json.dumps({
    "id": "abc123", "title": "Aperiodic Monotiles", "uploader": "3cycle",
    "duration": 1200, "webpage_url": "https://youtu.be/abc123",
    "comments": [{"id": "c1", "text": "this finally made tilings click", "author": "viewer"}],
})

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.000
an aperiodic monotile is a single shape

00:00:03.000 --> 00:00:06.000
an aperiodic monotile is a single shape
that tiles the plane without ever repeating
"""


def main() -> None:
    items = parse_video(INFO, VTT, fetched_at=1.0)
    print(f"parsed {len(items)} items from one video, each with a receipt:")
    for i in items:
        print(f"  {i.kind:<10} {i.id}  sha256={i.provenance.sha256[:12]}...  verify={i.verify()}")
    print()

    kept, dropped = filter_scope(items, ["tile", "monotile"])
    print(f"scope to ['tile','monotile']: kept {len(kept)}, dropped {dropped}")
    d = digest(kept)
    print(f"witnessed digest: {len(d.receipts)} receipts, seal {d.seal[:12]}..., verified {verify_digest(d)}")
    print()

    # tamper: swap a receipt's fingerprint, and the seal no longer matches
    bad = dataclasses.replace(d, receipts=({**d.receipts[0], "sha256": "0" * 64},) + d.receipts[1:])
    print(f"after tampering one receipt, digest verifies: {verify_digest(bad)}  <- caught")


if __name__ == "__main__":
    main()
