"""Interop: gather's web-data receipts as organ-bundle interchange entries.

The organ bundle is the shared spine index, forum, learn, crucible, and emet
already compose on: each entry carries a receipt by digest and reference, never
by embedded payload or granted authority. This module maps gather's receipts
(extraction, fetch, crawl ledger, search leads) into that entry shape, so a
gather crawl can feed index's context, a gather extraction can back a forum
evidence lane, and a gather provenance receipt can seed a learn lesson, all
through one contract.

Entry shape matches the proof-surface organ-bundle contract
(entry_id, organ_id, receipt_kind, status, payload_sha256, summary, payload_ref).
Cross-repo: registering the gather-* receipt kinds in proof-surface's closed
RECEIPT_KINDS is a separate, small change there; this module is self-contained
and validates the entries it emits.
"""
from __future__ import annotations

import re

from gather.item import content_hash

ORGAN = "gather"
# The registered umbrella kind on the shared spine. gather's web receipts compose
# as gather-corpus entries today; the specific subtype rides in the summary. (A
# dedicated gather-web kind in proof-surface's RECEIPT_KINDS is an optional
# refinement there.)
SPINE_KIND = "gather-corpus"
# A non-empty placeholder; a caller with a real clock should override generated_at.
PLACEHOLDER_TS = "1970-01-01T00:00:00Z"
STATUSES = frozenset({
    "pass", "fail", "unverified", "warn", "needs-human", "not-applicable", "unknown",
})
_HEX = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = ("entry_id", "organ_id", "receipt_kind", "status", "payload_sha256",
           "summary", "payload_ref")


def _entry(entry_id, subtype, status, payload_sha256, summary, ref) -> dict:
    return {
        "entry_id": entry_id, "organ_id": ORGAN, "receipt_kind": SPINE_KIND,
        "status": status, "payload_sha256": payload_sha256,
        "summary": f"[{subtype}] {summary}"[:160], "payload_ref": ref,
    }


def extraction_entry(ex, *, entry_id="gather-extract-1", ref="gather://extraction") -> dict:
    return _entry(entry_id, "extraction", "pass", ex.markdown_sha256,
                  f"{ex.url}: {len(ex.blocks)} block(s), title {ex.title!r}", ref)


def fetch_entry(receipt, *, entry_id="gather-fetch-1", ref="gather://fetch") -> dict:
    if receipt.not_modified:
        status, sha = "unverified", content_hash(receipt.url)
    else:
        status = "pass" if 200 <= receipt.status < 300 else "warn"
        sha = receipt.content_sha256 or content_hash(receipt.url)
    return _entry(entry_id, "fetch", status, sha,
                  f"{receipt.final_url}: HTTP {receipt.status}, {receipt.attempts} attempt(s)", ref)


def crawl_entry(ledger, *, entry_id="gather-crawl-1", ref="gather://crawl") -> dict:
    status = "pass" if ledger.verify() else "fail"
    return _entry(entry_id, "crawl", status, ledger.root_hash or content_hash(""),
                  f"ledger: {len(ledger.records)} page(s), chain {status}", ref)


def search_entry(receipt, *, entry_id="gather-search-1", ref="gather://search") -> dict:
    status = "pass" if receipt.status == "searched" else "unverified"
    return _entry(entry_id, "search-lead", status,
                  content_hash("|".join(receipt.urls())),
                  f"{receipt.query!r}: {len(receipt.hits)} lead(s) via {receipt.provider}", ref)


def bundle(entries, *, bundle_id="gather-bundle", generated_at=PLACEHOLDER_TS,
           subject="gather web-data receipts on the organ spine", edges=None) -> dict:
    return {
        "organ_bundle_version": "0.1", "bundle_id": bundle_id,
        "generated_at": generated_at or PLACEHOLDER_TS,
        "subject": subject, "entries": list(entries), "edges": list(edges or []),
        "notes": "gather receipts carried by digest + reference on the shared spine",
    }


def validate(b) -> list[str]:
    """Return a list of problems with the bundle's entries (empty == valid)."""
    issues: list[str] = []
    seen: set = set()
    for i, e in enumerate(b.get("entries", [])):
        for f in _FIELDS:
            if f not in e:
                issues.append(f"entry[{i}] missing {f}")
        if e.get("status") not in STATUSES:
            issues.append(f"entry[{i}] bad status {e.get('status')!r}")
        if not _HEX.match(str(e.get("payload_sha256", ""))):
            issues.append(f"entry[{i}] payload_sha256 is not a 64-hex digest")
        eid = e.get("entry_id")
        if eid in seen:
            issues.append(f"duplicate entry_id {eid!r}")
        seen.add(eid)
    return issues
