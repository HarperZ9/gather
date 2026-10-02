"""Closed source dispatch for pilot manifests.

Offline network sources replay approved fixtures through the adapters' pure
parsers.  Live and local sources use the existing ``Source`` implementations;
this module deliberately owns no transport or parsing logic of its own.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from gather.api import ApiSource, parse_api
from gather.arxiv import ArxivSource, parse_arxiv
from gather.browser import BrowserSource, parse_browser
from gather.docs import DocsSource
from gather.feed import FeedSource, parse_feed
from gather.item import Item
from gather.ocr import OcrSource
from gather.pdf import PdfSource
from gather.pilot_manifest import NETWORK_ADAPTERS, PilotManifest, PilotSource
from gather.scholar import PROVIDERS, ScholarSource
from gather.source import Source
from gather.transcribe import TranscribeSource
from gather.video import VideoSource, parse_video
from gather.web import WebSource, parse_web


class AdapterUnavailable(RuntimeError):
    """An optional executable or module required by an adapter is unavailable."""


@dataclass(frozen=True, slots=True)
class CapturedSource:
    items: tuple[Item, ...]
    extra_receipts: tuple[dict[str, object], ...] = ()
    extraction_html: str | None = None


ReplayFn = Callable[[PilotSource, Path, float], CapturedSource]
Factory = Callable[[Mapping[str, object]], Source]


class ScholarCaptureSource(Protocol):
    def fetch(self, target: str) -> list[Item]: ...

    def graph(self, target: str) -> tuple[list[Item], list[dict[str, object]]]: ...


def _replay_web(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    html = fixture.read_text(encoding="utf-8")
    return CapturedSource((parse_web(html, source.target, fetched_at=at),), extraction_html=html)


def _replay_feed(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    return CapturedSource(tuple(parse_feed(fixture.read_text(encoding="utf-8"), source.target, fetched_at=at)))


def _replay_arxiv(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    return CapturedSource(tuple(parse_arxiv(fixture.read_text(encoding="utf-8"), fetched_at=at)))


def _replay_scholar(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("scholar fixture must be an object keyed by provider")
    selected = _providers(source.options)

    def fixture_fetcher(provider: str, _url: str) -> str:
        if provider not in payload:
            raise ValueError(f"scholar fixture missing provider {provider!r}")
        return json.dumps(payload[provider], ensure_ascii=False, sort_keys=True)

    adapter = ScholarSource(
        providers=selected,
        federated=_bool_option(source.options, "federated", True),
        fetcher=fixture_fetcher,
        clock=lambda: at,
    )
    if _bool_option(source.options, "edges", False):
        items, edges = adapter.graph(source.target)
        return CapturedSource(tuple(items), tuple(edges))
    return CapturedSource(tuple(adapter.fetch(source.target)))


def _replay_video(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    return CapturedSource(
        tuple(
            parse_video(
                fixture.read_text(encoding="utf-8"),
                None,
                fetched_at=at,
                auto_captions=_bool_option(source.options, "auto_captions", False),
            )
        )
    )


def _replay_api(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    return CapturedSource(
        tuple(
            parse_api(
                fixture.read_text(encoding="utf-8"),
                source.target,
                fetched_at=at,
                items_key=_optional_string_option(source.options, "items_key"),
                id_key=_string_option(source.options, "id_key", "id"),
                title_key=_string_option(source.options, "title_key", "title"),
                text_key=_optional_string_option(source.options, "text_key"),
            )
        )
    )


def _replay_browser(source: PilotSource, fixture: Path, at: float) -> CapturedSource:
    html = fixture.read_text(encoding="utf-8")
    return CapturedSource((parse_browser(html, source.target, fetched_at=at),), extraction_html=html)


REPLAYERS: dict[str, ReplayFn] = {
    "web": _replay_web,
    "feed": _replay_feed,
    "arxiv": _replay_arxiv,
    "scholar": _replay_scholar,
    "video": _replay_video,
    "api": _replay_api,
    "browser": _replay_browser,
}


LOCAL_FACTORIES: dict[str, Factory] = {
    "docs": lambda _options: DocsSource(),
    "pdf": lambda _options: PdfSource(),
    "ocr": lambda options: OcrSource(lang=_string_option(options, "lang", "eng")),
    "transcribe": lambda options: TranscribeSource(model=_string_option(options, "model", "base")),
}


LIVE_FACTORIES: dict[str, Factory] = {
    "web": lambda _options: WebSource(),
    "feed": lambda _options: FeedSource(),
    "arxiv": lambda options: ArxivSource(max_results=_int_option(options, "max_results", 10)),
    "scholar": lambda options: ScholarSource(
        providers=_providers(options), federated=_bool_option(options, "federated", True)
    ),
    "video": lambda options: VideoSource(with_comments=_bool_option(options, "comments", False)),
    "api": lambda options: ApiSource(
        auth_env=_string_option(options, "auth_env", "GATHER_API_TOKEN"),
        items_key=_optional_string_option(options, "items_key"),
        id_key=_string_option(options, "id_key", "id"),
        title_key=_string_option(options, "title_key", "title"),
        text_key=_optional_string_option(options, "text_key"),
    ),
    "browser": lambda options: BrowserSource(
        browser=_string_option(options, "browser", "chromium"),
        no_sandbox=_bool_option(options, "no_sandbox", False),
    ),
}

_EXECUTABLE_ADAPTERS = frozenset({"browser", "ocr", "pdf", "transcribe", "video"})


def _bool_option(options: Mapping[str, object], name: str, default: bool) -> bool:
    value = options.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _int_option(options: Mapping[str, object], name: str, default: int) -> int:
    value = options.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _string_option(options: Mapping[str, object], name: str, default: str) -> str:
    value = options.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string_option(options: Mapping[str, object], name: str) -> str | None:
    value = options.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _providers(options: Mapping[str, object]) -> tuple[str, ...]:
    value = options.get("providers", PROVIDERS)
    if not isinstance(value, tuple) or not all(isinstance(provider, str) for provider in value):
        raise ValueError("providers must be a list of provider names")
    return value


def _fixture_for(source: PilotSource, *, refresh: bool) -> Path:
    fixture = source.resolved_refresh_fixture if refresh else None
    fixture = fixture or source.resolved_fixture
    if fixture is None:
        raise ValueError(f"offline {source.adapter} source requires a fixture")
    return fixture


def _local_target(source: PilotSource) -> str:
    if source.resolved_target is None:
        raise ValueError(f"local {source.adapter} source has no resolved target")
    return str(source.resolved_target)


def _fetch(factory: Factory, source: PilotSource, target: str) -> CapturedSource:
    try:
        return CapturedSource(tuple(factory(source.options).fetch(target)))
    except ModuleNotFoundError as error:
        raise AdapterUnavailable(f"{source.adapter} adapter module is unavailable") from error
    except FileNotFoundError as error:
        if source.adapter in _EXECUTABLE_ADAPTERS and error.filename:
            raise AdapterUnavailable(f"{source.adapter} adapter executable is unavailable") from error
        raise


def _capture_live_scholar(source: PilotSource) -> CapturedSource:
    factory = LIVE_FACTORIES["scholar"]
    try:
        adapter = cast(ScholarCaptureSource, factory(source.options))
        if _bool_option(source.options, "edges", False):
            items, edges = adapter.graph(source.target)
            return CapturedSource(tuple(items), tuple(edges))
        return CapturedSource(tuple(adapter.fetch(source.target)))
    except ModuleNotFoundError as error:
        raise AdapterUnavailable("scholar adapter module is unavailable") from error


def capture_source(
    source: PilotSource,
    manifest: PilotManifest,
    *,
    clock: Callable[[], float],
    refresh: bool = False,
) -> CapturedSource:
    """Capture one validated pilot source through its closed adapter dispatch."""
    if manifest.mode == "offline" and source.adapter in NETWORK_ADAPTERS:
        replayer = REPLAYERS.get(source.adapter)
        if replayer is None:
            raise AdapterUnavailable(f"offline adapter unavailable: {source.adapter}")
        return replayer(source, _fixture_for(source, refresh=refresh), float(clock()))
    if source.adapter in LOCAL_FACTORIES:
        # Docs sources use the manifest's portable target as the ref so corpus
        # digests are stable across platforms (no absolute filesystem paths).
        if source.adapter == "docs":
            def _docs_factory(_options: Mapping[str, object]) -> Source:
                return DocsSource(portable_ref=source.target)
            return _fetch(_docs_factory, source, _local_target(source))
        return _fetch(LOCAL_FACTORIES[source.adapter], source, _local_target(source))
    if manifest.mode == "live":
        if source.adapter == "scholar":
            return _capture_live_scholar(source)
        factory = LIVE_FACTORIES.get(source.adapter)
        if factory is None:
            raise AdapterUnavailable(f"live adapter unavailable: {source.adapter}")
        return _fetch(factory, source, source.target)
    raise AdapterUnavailable(f"offline adapter unavailable: {source.adapter}")
