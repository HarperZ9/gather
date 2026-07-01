from __future__ import annotations

from collections.abc import Mapping

from gather.item import Item, make_item

SCHEMA = "project-telos.browser-evidence/v1"
METHOD = "browser-evidence"


def parse_browser_evidence(packet: Mapping, *, fetched_at: float) -> Item:
    """Import a Telos browser-evidence packet as a direct source item.

    Gather stores compact refs and verdicts, never raw browser payloads.
    """
    if packet.get("schema") != SCHEMA:
        raise ValueError("browser evidence schema mismatch")
    target_ref = str(packet.get("target_ref") or "")
    if not target_ref:
        raise ValueError("browser evidence packet missing target_ref")
    after = packet.get("after") if isinstance(packet.get("after"), Mapping) else {}
    verification = packet.get("verification") if isinstance(packet.get("verification"), Mapping) else {}
    title = str(after.get("title") or after.get("url") or target_ref)
    text = _summary(packet, after, verification)
    meta = {
        "schema": SCHEMA,
        "mode": packet.get("mode"),
        "tool": packet.get("tool"),
        "target_ref": target_ref,
        "action_receipt_ref": packet.get("action_receipt_ref"),
        "after": _safe_snapshot(after),
        "artifact_hashes": list(packet.get("artifact_hashes") or []),
        "side_effect": packet.get("side_effect"),
        "verification": dict(verification),
    }
    return make_item(
        kind="webpage",
        id=target_ref,
        title=title,
        text=text,
        source="browser",
        ref=target_ref,
        method=METHOD,
        fetched_at=fetched_at,
        meta=meta,
    )


def _summary(packet: Mapping, after: Mapping, verification: Mapping) -> str:
    return "\n".join([
        f"browser-evidence: {packet.get('mode') or 'unknown'}",
        f"url: {after.get('url') or packet.get('target_ref') or ''}",
        f"title: {after.get('title') or ''}",
        f"text_digest: {after.get('text_digest') or ''}",
        f"verification: {verification.get('verdict') or 'UNVERIFIABLE'}",
    ])


def _safe_snapshot(snapshot: Mapping) -> dict:
    allowed = ("url", "url_digest", "title", "dom_snapshot_ref", "text_digest", "screenshot_ref")
    return {key: snapshot.get(key) for key in allowed if key in snapshot}
