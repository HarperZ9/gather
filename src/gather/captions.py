"""Pick exactly one caption track from a yt-dlp info dict. Pure: no network.

A yt-dlp info dict lists every track YouTube offers: manual ``subtitles`` and machine
``automatic_captions``, including dozens of machine translations. Downloading a pattern such as
``en.*`` fetches several of them per video, each one a request to the caption endpoint, and can
pick a translation over the original. Choosing one track up front keeps caption requests to one
per video and keeps the transcript's method honest. For each wanted language, in order:

1. a manual track in that language (exact code first, then a regional variant);
2. the original-language auto-caption (``en-orig``, or a regional ``en-US-orig``);
3. a plain auto-caption track only when it is not a machine translation (no ``tlang``).

A translated auto-caption is refused, not relabeled: it is derived text, and the transcript
contract records ``auto-caption`` for a direct machine transcript of the audio.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

NONE_OFFERED = "none-offered"
TRANSLATION_ONLY = "translation-only"
NO_MATCHING_LANGUAGE = "no-matching-language"

_NOT_CAPTIONS = frozenset({"live_chat"})  # yt-dlp lists stream chat replay under subtitles


@dataclass(frozen=True, slots=True)
class CaptionChoice:
    lang: str   # the track key as yt-dlp names it: "en", "en-US", "en-orig"
    auto: bool  # machine-generated


@dataclass(frozen=True, slots=True)
class CaptionPick:
    choice: CaptionChoice | None
    reason: str | None = None  # a code when no track was chosen
    detail: str = ""


def _tracks(info: dict, key: str) -> dict[str, list]:
    raw = info.get(key) or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k not in _NOT_CAPTIONS and isinstance(v, list) and v}


def _is_translation(formats: list) -> bool:
    for fmt in formats:
        url = fmt.get("url") if isinstance(fmt, dict) else None
        if isinstance(url, str) and parse_qs(urlsplit(url).query).get("tlang"):
            return True
    return False


def _pick_manual(manual: dict[str, list], lang: str) -> str | None:
    if lang in manual:
        return lang
    regional = sorted(k for k in manual if k.startswith(lang + "-"))
    return regional[0] if regional else None


def _pick_auto(auto: dict[str, list], lang: str) -> str | None:
    if f"{lang}-orig" in auto:
        return f"{lang}-orig"
    orig = re.compile(rf"^{re.escape(lang)}(?:-[A-Za-z0-9]+)+-orig$")
    regional = sorted(k for k in auto if orig.match(k))
    if regional:
        return regional[0]
    if lang in auto and not _is_translation(auto[lang]):
        return lang
    return None


def select_caption_track(info: dict, langs: Sequence[str] = ("en",)) -> CaptionPick:
    """Choose one caption track: languages in ``langs`` order, and within a language, manual
    before auto."""
    manual = _tracks(info, "subtitles")
    auto = _tracks(info, "automatic_captions")
    for lang in langs:
        key = _pick_manual(manual, lang)
        if key:
            return CaptionPick(CaptionChoice(key, auto=False))
        key = _pick_auto(auto, lang)
        if key:
            return CaptionPick(CaptionChoice(key, auto=True))
    if not manual and not auto:
        return CaptionPick(None, NONE_OFFERED, "the video offers no caption tracks")
    originals = sorted(k[: -len("-orig")] for k in auto if k.endswith("-orig"))
    if any(lang in auto for lang in langs):
        return CaptionPick(None, TRANSLATION_ONLY,
                           f"only a machine translation is offered; original: {', '.join(originals) or 'unknown'}")
    offered = sorted(manual) + [k for k in originals if k not in manual]
    return CaptionPick(None, NO_MATCHING_LANGUAGE,
                       f"no {'/'.join(langs)} track; offered: {', '.join(offered[:8]) or 'none'}")
