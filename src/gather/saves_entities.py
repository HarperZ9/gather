"""Entities in an item's text, found by regular expression only.

Seven types: ``url``, ``doi``, ``arxiv``, ``handle``, ``hashtag``, ``date`` and ``quantity``. The
patterns are fixed, so the same text always gives the same rows. They miss entities written in
other forms and they over-match (``5 A`` reads as five amperes whatever the sentence meant). No
model and no lookup is involved, and nothing found is fetched.
"""

from __future__ import annotations

import datetime
import re

TYPES = ("url", "doi", "arxiv", "handle", "hashtag", "date", "quantity")
_TAIL = ".,;:!?)]}'\""

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_URL_PARTS = re.compile(r"(https?)://([^/?#]*)(.*)", re.I | re.S)
_DOI = re.compile(r"(?<![\w.])10\.\d{4,9}/[^\s\"<>]+")
_ARXIV = (
    re.compile(r"arxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)(?!\d)", re.I),
    re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", re.I),
    re.compile(r"(?i:arxiv):\s*([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?!\d)"),
)
_HANDLE = re.compile(r"(?<![\w@/.])@([A-Za-z0-9_]{1,30})(?![\w@])|(?<![\w/.])([ur])/([A-Za-z0-9_-]{2,30})(?![\w/])")
_HASHTAG = re.compile(r"(?<![\w&/#])#(\w*[^\W\d_]\w*)")

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")
_MONTH = "(" + "|".join(f"{m}|{m[:3]}" if len(m) > 3 else m for m in _MONTHS) + r"|sept)\.?"
_ORD = r"(?:st|nd|rd|th)?"
_DATE_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?!\d|-\d)")
_DATE_DMY = re.compile(rf"(?<![\w-])(\d{{1,2}}){_ORD}\s+{_MONTH}\s+(\d{{4}})(?!\d)", re.I)
_DATE_MDY = re.compile(rf"(?<![\w-]){_MONTH}\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})(?!\d)", re.I)

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MULT = r"thousand|million|billion|trillion"
_CODES = r"USD|EUR|GBP|JPY|CNY|INR|CAD|AUD|CHF"
_SYMBOLS = r"[$€£¥₹]"
UNITS = ("km/h", "kbps", "Mbps", "Gbps", "kWh", "mph", "kHz", "MHz", "GHz", "bps", "fps", "min", "km", "cm", "mm",
         "nm", "kg", "mg", "ms", "ns", "µs", "Hz", "kW", "MW", "°C", "°F", "GB", "MB", "TB", "kB", "KB", "px", "dB",
         "mL", "m", "g", "s", "h", "W", "V", "A", "K", "L")
_UNIT = "|".join(re.escape(u) for u in UNITS)
_QUANTITY = re.compile(
    rf"(?:(?P<c>{_SYMBOLS}|\b(?:{_CODES}))\s?(?P<n1>{_NUM})(?:\s?(?P<m1>{_MULT}))?(?!\w)"
    rf"|(?<![\w.,$€£¥₹])(?P<n2>{_NUM})(?:\s?(?P<m2>{_MULT})(?!\w))?"
    rf"(?:\s?(?P<u>%|{_SYMBOLS}|(?:percent|{_CODES}|{_UNIT})(?!\w)))?)")


def _url(text: str):
    for m in _URL.finditer(text):
        value = m.group(0).rstrip(_TAIL)
        parts = _URL_PARTS.fullmatch(value)
        if parts and parts.group(2):
            yield value, f"{parts.group(1).lower()}://{parts.group(2).lower()}{parts.group(3)}"


def _doi(text: str):
    for m in _DOI.finditer(text):
        value = m.group(0).rstrip(_TAIL)
        yield value, value.lower()


def _arxiv(text: str):
    for pattern in _ARXIV:
        for m in pattern.finditer(text):
            yield m.group(1), m.group(1)


def _handle(text: str):
    for m in _HANDLE.finditer(text):
        yield m.group(0), m.group(0).lower()


def _hashtag(text: str):
    for m in _HASHTAG.finditer(text):
        yield m.group(0), m.group(0).lower()


def _month_number(name: str) -> int:
    key = name.lower().rstrip(".")[:3]
    return next(i + 1 for i, m in enumerate(_MONTHS) if m.startswith(key))


def _date(text: str):
    found = [(m.start(), m.group(0), (m.group(1), m.group(2), m.group(3))) for m in _DATE_ISO.finditer(text)]
    found += [(m.start(), m.group(0), (m.group(3), _month_number(m.group(2)), m.group(1)))
              for m in _DATE_DMY.finditer(text)]
    found += [(m.start(), m.group(0), (m.group(3), _month_number(m.group(1)), m.group(2)))
              for m in _DATE_MDY.finditer(text)]
    for _, value, (year, month, day) in sorted(found):
        try:
            yield value, datetime.date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue  # an impossible date such as 2026-02-30 is not a date entity


def _quantity(text: str):
    for m in _QUANTITY.finditer(text):
        number = (m.group("n1") or m.group("n2")).replace(",", "")
        unit = " ".join(p for p in (m.group("m1") or m.group("m2"), m.group("c") or m.group("u")) if p)
        if unit:
            yield m.group(0), f"{number} {unit}"


_FULL_TEXT = (("url", _url), ("doi", _doi), ("arxiv", _arxiv))
_NO_URLS = (("handle", _handle), ("hashtag", _hashtag), ("date", _date), ("quantity", _quantity))


def extract_entities(text: str) -> list[dict]:
    """Rows of type, value, normalized and count, one per (type, normalized), sorted by type then value.

    ``value`` is the first form seen in the text and ``count`` is how many times the normalized form
    occurs. Handles, hashtags, dates and quantities are not read from inside an address.
    """
    without_urls = _URL.sub(" ", text)
    rows: dict[tuple[str, str], dict] = {}
    for group, source in ((_FULL_TEXT, text), (_NO_URLS, without_urls)):
        for kind, finder in group:
            for value, normalized in finder(source):
                row = rows.setdefault((kind, normalized), {"type": kind, "value": value, "normalized": normalized, "count": 0})
                row["count"] += 1
    return sorted(rows.values(), key=lambda r: (r["type"], r["value"], r["normalized"]))
