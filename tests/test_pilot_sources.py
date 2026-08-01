import json
import socket
from pathlib import Path

import pytest

from gather.item import content_hash, make_item
from gather.pilot_manifest import PilotManifest, load_pilot_manifest
from gather.pilot_sources import CapturedSource, capture_source

WEB_HTML = "<html><title>Web title</title><body><p>Web body</p></body></html>"
FEED_XML = "<rss><channel><title>Feed</title><item><guid>post-1</guid><link>https://example.com/post</link><title>Feed title</title><description>Feed body</description></item></channel></rss>"
ARXIV_XML = "<feed xmlns=\"http://www.w3.org/2005/Atom\"><entry><id>http://arxiv.org/abs/2401.00001</id><title>Arxiv title</title><summary>Arxiv abstract</summary></entry></feed>"
SCHOLAR_JSON = json.dumps(
    {
        "openalex": {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "10.1234/pilot",
                    "title": "Scholar title",
                    "publication_year": 2026,
                    "authorships": [],
                    "abstract_inverted_index": {"Scholar": [0], "abstract": [1]},
                    "referenced_works": ["https://openalex.org/W2"],
                }
            ]
        }
    }
)
VIDEO_JSON = json.dumps(
    {
        "id": "video-1",
        "title": "Video title",
        "uploader": "Author",
        "duration": 9,
        "upload_date": "20260730",
        "view_count": 1,
        "webpage_url": "https://example.com/watch",
    }
)
API_JSON = json.dumps({"results": [{"id": "api-1", "title": "API title", "body": "API body"}]})


def load_fixture_manifest(
    tmp_path: Path,
    *,
    adapter: str,
    fixture_text: str = WEB_HTML,
    options: dict[str, object] | None = None,
    refresh_text: str | None = None,
    mode: str = "offline",
) -> PilotManifest:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "source.fixture").write_text(fixture_text, encoding="utf-8")
    refresh_fixture: str | None = None
    if refresh_text is not None:
        (fixtures / "refresh.fixture").write_text(refresh_text, encoding="utf-8")
        refresh_fixture = "fixtures/refresh.fixture"
    host = "export.arxiv.org" if adapter == "arxiv" else "api.openalex.org" if adapter == "scholar" else "example.com"
    source = {
        "id": "source-one",
        "adapter": adapter,
        "target": f"https://{host}/evidence",
        "fixture": "fixtures/source.fixture" if mode == "offline" else None,
        "refresh_fixture": refresh_fixture if mode == "offline" else None,
        "visibility": "private",
        "monitor": refresh_fixture is not None,
        "required": True,
        "extraction": None,
        "options": options or {},
    }
    if adapter in {"web", "browser"}:
        source["extraction"] = {"fields": {"title": {"selector": "title"}}}
    manifest_data = {
        "schema": "gather.pilot-manifest/1",
        "pilot_id": "pilot-one",
        "title": "Offline pilot",
        "mode": mode,
        "deployment": {"mode": "workstation", "custodian": "customer"},
        "policy": {
            "allowed_hosts": [host],
            "trusted_browser_hosts": [host] if adapter == "browser" else [],
            "allowed_local_roots": ["fixtures"],
            "enabled_adapters": [adapter],
            "credentials": [],
            "report_private_content": False,
        },
        "missions": [{"id": "mission-one", "title": "Evidence", "sources": [source]}],
    }
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return load_pilot_manifest(path)


@pytest.mark.parametrize(
    ("adapter", "fixture_text", "options", "expected_source", "expected_method", "expected_ref", "expected_hash"),
    [
        ("web", WEB_HTML, {}, "web", "http-get", "https://example.com/evidence", content_hash("Web body")),
        ("feed", FEED_XML, {}, "feed", "feed", "https://example.com/post", content_hash("Feed body")),
        ("arxiv", ARXIV_XML, {}, "arxiv", "arxiv-api", "http://arxiv.org/abs/2401.00001", content_hash("Arxiv abstract")),
        ("scholar", SCHOLAR_JSON, {"providers": ["openalex"], "federated": False, "edges": True}, "scholar", "openalex-api", "10.1234/pilot", content_hash("Scholar abstract")),
        ("video", VIDEO_JSON, {}, "video", "yt-dlp", "video-1", content_hash('{"duration": 9, "upload_date": "20260730", "uploader": "Author", "view_count": 1, "webpage_url": "https://example.com/watch"}')),
        ("api", API_JSON, {"items_key": "results", "text_key": "body"}, "api", "api-get", "https://example.com/evidence", content_hash("API body")),
        ("browser", WEB_HTML, {}, "browser", "browser-extract", "https://example.com/evidence", content_hash("Web body")),
    ],
)
def test_offline_replay_uses_the_existing_adapter_parser(
    tmp_path: Path,
    adapter: str,
    fixture_text: str,
    options: dict[str, object],
    expected_source: str,
    expected_method: str,
    expected_ref: str,
    expected_hash: str,
) -> None:
    """A wrong replayer/parser or receipt shape fails this boundary contract."""
    manifest = load_fixture_manifest(tmp_path, adapter=adapter, fixture_text=fixture_text, options=options)

    result = capture_source(manifest.missions[0].sources[0], manifest, clock=lambda: 1_700_000_000.0)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.provenance.source == expected_source
    assert item.provenance.method == expected_method
    assert item.provenance.ref == expected_ref
    assert item.provenance.sha256 == expected_hash
    if adapter == "scholar":
        assert len(result.extra_receipts) == 1
    if adapter in {"web", "browser"}:
        assert result.extraction_html == fixture_text


def test_offline_replay_never_opens_a_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing a pure replayer with a live source would open the forbidden socket."""
    manifest = load_fixture_manifest(tmp_path, adapter="web")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline replay opened a socket")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = capture_source(manifest.missions[0].sources[0], manifest, clock=lambda: 1_700_000_000.0)
    assert len(result.items) == 1


def test_refresh_replay_uses_refresh_fixture_and_keeps_html(tmp_path: Path) -> None:
    """Ignoring refresh_fixture would replay stale web evidence and extraction markup."""
    refreshed = "<html><title>New title</title><body><p>New body</p></body></html>"
    manifest = load_fixture_manifest(tmp_path, adapter="web", refresh_text=refreshed)

    result = capture_source(manifest.missions[0].sources[0], manifest, clock=lambda: 1_700_000_000.0, refresh=True)

    assert result.items[0].text == "New body"
    assert result.items[0].provenance.sha256 == content_hash("New body")
    assert result.extraction_html == refreshed


def test_live_scholar_edges_are_returned_only_as_extra_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Using fetch for live edges would silently discard graph evidence."""
    import gather.pilot_sources as pilot_sources

    manifest = load_fixture_manifest(
        tmp_path,
        adapter="scholar",
        mode="live",
        options={"providers": ["openalex"], "edges": True},
    )
    graph_item = make_item(
        kind="paper",
        id="graph-item",
        title="Graph item",
        text="graph item",
        source="scholar",
        ref="graph-item",
        method="openalex-api",
        fetched_at=1.0,
    )
    fetch_item = make_item(
        kind="paper",
        id="fetch-item",
        title="Fetch item",
        text="fetch item",
        source="scholar",
        ref="fetch-item",
        method="openalex-api",
        fetched_at=1.0,
    )

    class FakeScholar:
        def fetch(self, _target: str) -> list:
            return [fetch_item]

        def graph(self, _target: str) -> tuple[list, list[dict[str, object]]]:
            return [graph_item], [{"id": "citation-1", "method": "citation-edge"}]

    monkeypatch.setitem(pilot_sources.LIVE_FACTORIES, "scholar", lambda _options: FakeScholar())

    edges = capture_source(manifest.missions[0].sources[0], manifest, clock=lambda: 1.0)

    assert isinstance(edges, CapturedSource)
    assert edges.items == (graph_item,)
    assert edges.extra_receipts == ({"id": "citation-1", "method": "citation-edge"},)

    plain_manifest = load_fixture_manifest(
        tmp_path / "plain",
        adapter="scholar",
        mode="live",
        options={"providers": ["openalex"], "edges": False},
    )
    plain = capture_source(plain_manifest.missions[0].sources[0], plain_manifest, clock=lambda: 1.0)
    assert plain.items == (fetch_item,)
    assert plain.extra_receipts == ()
