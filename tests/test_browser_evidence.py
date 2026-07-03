from gather.browser_evidence import parse_browser_evidence
from gather.method import DIRECT, directness

PACKET = {
    "schema": "project-telos.browser-evidence/v1",
    "tool": "telos.browser.evidence",
    "mode": "research-capture",
    "session_ref": "browser-session:fixture",
    "target_ref": "url:sha256:abc",
    "action_receipt_ref": "receipt:fixture",
    "action": {"kind": "browser.navigate", "args_hash": "args:sha256:def"},
    "before": {
        "url": "https://example.com",
        "title": "Before",
        "raw_dom": "<html>must not leak</html>",
        "dom_snapshot_ref": "artifact:before-dom.html",
    },
    "after": {
        "url": "https://example.com",
        "title": "Example Domain",
        "text_digest": "text:sha256:123",
        "screenshot_ref": "artifact:after.png",
        "raw_dom": "<html>must not leak</html>",
    },
    "artifact_hashes": [{"ref": "artifact:after.png", "hash": "sha256:456"}],
    "side_effect": {"class": "read", "external_write": False, "reversible": True},
    "verification": {"verdict": "MATCH", "ref": "crucible:shape"},
}


def test_browser_evidence_packet_becomes_direct_gather_item_without_raw_dom():
    item = parse_browser_evidence(PACKET, fetched_at=1.0)

    assert item.kind == "webpage"
    assert item.id == "url:sha256:abc"
    assert item.title == "Example Domain"
    assert item.provenance.source == "browser"
    assert item.provenance.method == "browser-evidence"
    assert item.provenance.ref == "url:sha256:abc"
    assert directness("browser-evidence") == DIRECT
    assert item.meta["schema"] == "project-telos.browser-evidence/v1"
    assert item.meta["mode"] == "research-capture"
    assert item.meta["verification"]["verdict"] == "MATCH"
    assert item.meta["artifact_hashes"][0]["ref"] == "artifact:after.png"
    assert "raw_dom" not in str(item)
