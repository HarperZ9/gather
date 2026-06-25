from __future__ import annotations

import glob
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from gather.item import Item, make_item

_VTT_TAG = re.compile(r"<[^>]+>")


def transcript_from_vtt(vtt: str) -> str:
    """Plain text from a WebVTT caption file.

    Drops the header, NOTE blocks, cue-timing lines, and inline tags (including the
    inline timestamp tags that YouTube auto-captions carry), and decodes HTML entities.
    It then collapses the rolling-window duplication auto-captions produce: when a line
    is a prefix-extension of the previous emitted line (the same caption still scrolling
    in) the previous line is replaced rather than appended, and an exact consecutive
    duplicate is dropped. Best-effort for auto-captions; manual subtitles pass through
    cleanly. Pure and deterministic. One honest caveat: a line genuinely repeated back to
    back, or one line that is a true prefix of the next distinct line, is also collapsed.
    """
    out: list[str] = []
    in_note = False
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line:
            in_note = False  # a blank line ends a NOTE block
            continue
        if in_note:
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if line.startswith("NOTE"):
            in_note = True
            continue
        if "-->" in line:
            continue
        line = html.unescape(_VTT_TAG.sub("", line)).strip()
        if not line:
            continue
        if out and line.startswith(out[-1]):
            out[-1] = line  # same caption still rolling in: replace, do not ladder
        elif not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def parse_video(
    info_json: str,
    vtt: str | None,
    *,
    fetched_at: float,
    method: str = "yt-dlp",
    transcript_method: str | None = None,
) -> list[Item]:
    """Turn a yt-dlp info.json (and optional .vtt captions) into Items. Pure: no network.

    Produces a metadata Item, a transcript Item when captions are present, and a comment
    Item per comment yt-dlp captured. ``method`` stamps the metadata and comments;
    ``transcript_method`` stamps the transcript (default ``method``) so an auto-caption
    transcript can record that it is machine transcription, not a manual one. Each item
    gets a provenance receipt. Raises ValueError on malformed yt-dlp JSON.
    """
    try:
        info = json.loads(info_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid yt-dlp JSON: {exc}") from exc
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
                source="video", ref=vid, method=transcript_method or method, fetched_at=fetched_at,
                meta={"uploader": uploader},
            )
        )
    for c in info.get("comments") or []:
        ctext = str(c.get("text", ""))
        if ctext:
            items.append(
                make_item(
                    kind="comment", id=str(c.get("id", "")), title=f"comment on {title}", text=ctext,
                    source="video", ref=vid, method=method, fetched_at=fetched_at,
                    meta={"author": str(c.get("author", ""))},
                )
            )
    return items


class VideoSource:
    """Video intake (metadata, captions, comments) via the yt-dlp CLI.

    The isolated impure edge: it shells out to ``yt-dlp`` (an external tool, not a Python
    dependency, the way Forum's SubprocessExecutor calls a model CLI) and parses the
    result with the pure parse_video. Network and the tool live only here; the parsing is
    tested without either. fetch() needs yt-dlp on PATH. It prefers manual subtitles and
    falls back to auto-captions, recording which one fed the transcript.
    """

    name = "video"

    def __init__(self, *, clock=time.time, yt_dlp: str = "yt-dlp", with_comments: bool = False, timeout: float = 120.0) -> None:
        self._clock = clock
        self._yt_dlp = yt_dlp
        self._with_comments = with_comments
        self._timeout = timeout  # per yt-dlp call; fetch makes up to three calls

    def fetch(self, target: str) -> list[Item]:
        """Fetch one video's metadata, captions, and (optionally) comments via yt-dlp.

        Needs yt-dlp on PATH and network access. Raises RuntimeError if the metadata call
        fails. Caption failures are reported to stderr, not silently treated as absent.
        """
        cmd = [self._yt_dlp, "--dump-single-json", "--skip-download"]
        if self._with_comments:
            cmd.append("--write-comments")
        cmd.append(target)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()[:200]}")
        vtt, is_auto = self._fetch_captions(target)
        transcript_method = "auto-caption" if is_auto else self._yt_dlp
        return parse_video(
            proc.stdout, vtt, fetched_at=float(self._clock()), method=self._yt_dlp,
            transcript_method=transcript_method,
        )

    def _fetch_captions(self, target: str) -> tuple[str | None, bool]:
        """Prefer manual subtitles; fall back to auto-captions. Returns ``(vtt, is_auto)``.

        Manual subs are a more direct transcript than machine auto-captions, so they are
        tried first and the caller stamps the transcript's method by which was used.
        """
        manual = self._download_subs(target, auto=False)
        if manual is not None:
            return manual, False
        auto = self._download_subs(target, auto=True)
        if auto is not None:
            return auto, True
        return None, False

    def _download_subs(self, target: str, *, auto: bool) -> str | None:
        flag = "--write-auto-subs" if auto else "--write-subs"
        with tempfile.TemporaryDirectory() as d:
            cmd = [
                self._yt_dlp, "--skip-download", flag, "--sub-langs", "en.*",
                "--sub-format", "vtt", "-o", os.path.join(d, "%(id)s.%(ext)s"), target,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
            vtts = sorted(glob.glob(os.path.join(d, "*.vtt")))
            if not vtts:
                if proc.returncode != 0:
                    kind = "auto" if auto else "manual"
                    print(f"gather: yt-dlp {kind} subs failed: {proc.stderr.strip()[:160]}", file=sys.stderr)
                return None
            with open(vtts[0], encoding="utf-8") as f:
                return f.read()
