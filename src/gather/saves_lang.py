"""A language tag by fixed rule. This is a rule, not a classifier.

``detect_language`` counts Unicode scripts and, for Latin script, hits in a short stop-word list
per language. It returns a BCP 47 primary tag only for clear cases and ``und`` for everything
else: short text, mixed scripts, Cyrillic without a letter that separates Russian from Ukrainian,
Arabic script with Persian letters, and Latin text outside the six listed languages. It will be
wrong on some text. Use the sidecar's own ``lang`` when the page declared one.
"""

from __future__ import annotations

import re

_STRIP = re.compile(r"https?://\S+|[@#]\w+")
_WORD = re.compile(r"[^\W\d_]+")
_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")

_SCRIPTS = (
    ("kana", ((0x3040, 0x30FF), (0x31F0, 0x31FF))),
    ("hangul", ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))),
    ("han", ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))),
    ("cyrillic", ((0x0400, 0x04FF),)),
    ("arabic", ((0x0600, 0x06FF), (0x0750, 0x077F))),
    ("hebrew", ((0x0590, 0x05FF),)),
    ("devanagari", ((0x0900, 0x097F),)),
    ("greek", ((0x0370, 0x03FF),)),
    ("thai", ((0x0E00, 0x0E7F),)),
    ("latin", ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F))),
)
_SINGLE = {"arabic": "ar", "hebrew": "he", "devanagari": "hi", "greek": "el", "thai": "th"}
_UKRAINIAN, _RUSSIAN, _PERSIAN = set("іїєґ"), set("ыэъё"), set("پچژگ")

_STOP = {
    "en": "the and of to is in that it for with was this are not you have be on as but from they "
          "what which their would there has been will about",
    "es": "el los las que y en es por con para una del no se su lo como más pero sus le ya este "
          "porque muy también hay está son todo",
    "fr": "le les des et est que dans pour pas une sur au avec qui ce il ne se plus par mais nous "
          "vous sont cette aux être comme ont du",
    "de": "der die das und ist nicht ein eine zu den mit von auf für sich auch es dem im des wird "
          "sind oder aber wie wir ich noch nach bei",
    "pt": "o os as que e em é para com não uma um do da dos das no na por mais como mas foi ao ele "
          "seu sua também são está",
    "it": "il lo gli che e di è per non una un con del della sono ma più come anche si nel alla le "
          "dei questo ha ho io ci perché",
}
STOP_WORDS = {lang: frozenset(words.split()) for lang, words in _STOP.items()}
MIN_HITS, MARGIN = 3, 2


def sidecar_language(value) -> str:
    """The primary subtag of a well formed BCP 47 tag, lower case, else an empty string."""
    if isinstance(value, str) and _TAG.fullmatch(value.strip()):
        return value.strip().split("-")[0].lower()
    return ""


def script_counts(text: str) -> dict[str, int]:
    counts = {name: 0 for name, _ in _SCRIPTS}
    for ch in text:
        code = ord(ch)
        for name, ranges in _SCRIPTS:
            if any(lo <= code <= hi for lo, hi in ranges):
                counts[name] += 1
                break
    return counts


def _cyrillic(text: str) -> str:
    lower = text.lower()
    uk = sum(lower.count(ch) for ch in _UKRAINIAN)
    ru = sum(lower.count(ch) for ch in _RUSSIAN)
    if uk > ru:
        return "uk"
    return "ru" if ru > uk else "und"


def _latin(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text)]
    hits = sorted(((sum(1 for w in words if w in stop), lang) for lang, stop in STOP_WORDS.items()), reverse=True)
    (best, lang), (second, _) = hits[0], hits[1]
    return lang if best >= MIN_HITS and best - second >= MARGIN else "und"


def detect_language(text: str) -> str:
    """A BCP 47 primary tag for a clear case, else ``und``. A rule, not a classifier."""
    text = _STRIP.sub(" ", text)
    counts = script_counts(text)
    total = sum(counts.values())
    if not total:
        return "und"
    cjk = counts["kana"] + counts["han"] + counts["hangul"]
    if cjk * 2 > total:
        if counts["kana"]:
            return "ja"
        return "ko" if counts["hangul"] else "zh"
    name = max(counts, key=lambda k: counts[k])
    if counts[name] * 2 <= total:
        return "und"
    if name == "cyrillic":
        return _cyrillic(text)
    if name == "latin":
        return _latin(text)
    if name == "arabic" and any(ch in _PERSIAN for ch in text):
        return "und"
    return _SINGLE.get(name, "und")
