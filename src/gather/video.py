from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import tempfile
import time

from gather.item import Item, make_item

_VTT_TAG = re.compile(r"<[^>]+>")


def transcript_from_vtt(vtt: str) -> str:
    """Plain text from a WebVTT caption file.

    Drops the header, cue-timing lines, inline tags, and consecutive duplicate lines
    (auto-captions repeat each line as they scroll). Pure and deterministic, so the
    transcript is reproducible from the same vtt.
    """
    out: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        line = _VTT_TAG.sub("", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


def parse_video(info_json: str, vtt: str | None, *, fetched_at: float, method: str = "yt-dlp") -> list[Item]:
    """Turn a yt-dlp info.json (and optional .vtt captions) into Items. Pure: no network.

    Produces a metadata Item, a transcript Item when captions are present, and a comment
    Item per comment yt-dlp captured. This is the testable heart of the video adapter;
    fetch() is the impure shell around it. Each item gets a provenance receipt.
    """
    info = json.loads(info_json)
    vid = str(info.get("id", ""))
    title = str(info.get("title", ""))
    uploader = str(info.get("uploader") or info.get("channel") or "")
    meta_text = json.dumps(
        {
            "uploader": uploader,
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "view_count": info.get("view_count"),
            "webpage_url": info.get("webpage_url"),
        },
        sort_keys=True,
    )
    items = [
        make_item(
            kind="metadata", id=vid, title=title, text=meta_text,
            source="video", ref=vid, method=method, fetched_at=fetched_at, meta={"uploader": uploader},
        )
    ]
    if vtt:
        items.append(
            make_item(
                kind="transcript", id=vid, title=title, text=transcript_from_vtt(vtt),
                source="video", ref=vid, method=method, fetched_at=fetched_at, meta={"uploader": uploader},
            )
        )
    for c in info.get("comments") or []:
        ctext = str(c.get("text", ""))
        if ctext:
            items.append(
                make_item(
                    kind="comment", id=str(c.get("id", "")), title=f"comment on {title}", text=ctext,
                    source="video", ref=vid, method=method, fetched_at=fetched_at, meta={"author": c.get("author")},
                )
            )
    return items


class VideoSource:
    """Video intake (metadata, captions, comments) via the yt-dlp CLI.

    The isolated impure edge: it shells out to ``yt-dlp`` (an external tool, not a Python
    dependency, the way Forum's SubprocessExecutor calls a model CLI) and parses the
    result with the pure parse_video. Network and the tool live only here; the parsing
    is tested without either. fetch() needs yt-dlp on PATH.
    """

    name = "video"

    def __init__(self, *, clock=time.time, yt_dlp: str = "yt-dlp", with_comments: bool = False, timeout: float = 120.0) -> None:
        self._clock = clock
        self._yt_dlp = yt_dlp
        self._with_comments = with_comments
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        """Fetch one video's metadata, captions, and (optionally) comments via yt-dlp.

        Needs yt-dlp on PATH and network access. Raises RuntimeError if yt-dlp fails.
        """
        cmd = [self._yt_dlp, "--dump-single-json", "--skip-download"]
        if self._with_comments:
            cmd.append("--write-comments")
        cmd.append(target)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()[:200]}")
        vtt = self._fetch_captions(target)
        return parse_video(proc.stdout, vtt, fetched_at=float(self._clock()), method=self._yt_dlp)

    def _fetch_captions(self, target: str) -> str | None:
        """Best-effort: download English subs (manual or auto) to a temp dir and read the vtt."""
        with tempfile.TemporaryDirectory() as d:
            cmd = [
                self._yt_dlp, "--skip-download", "--write-auto-subs", "--write-subs",
                "--sub-langs", "en.*", "--sub-format", "vtt", "-o", os.path.join(d, "%(id)s.%(ext)s"), target,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
            vtts = sorted(glob.glob(os.path.join(d, "*.vtt")))
            if not vtts:
                return None
            with open(vtts[0], encoding="utf-8") as f:
                return f.read()
