"""The per-pass ledger and run summary for channel intake.

Each pass (``metadata``, ``metadata-comments``, ``captions``, ``full``, ``full-comments``)
appends one JSON row per attempted entry to ``<store>/intake/ledger-<pass>.jsonl``. The ledger
is the resume record: an entry whose latest row is settled is skipped on the next run, and an
entry whose latest row is not (throttled, timed out, stopped) is tried again. Summaries are
computed from rows alone, so a resumed pass reports its whole state, not just the last run.

Comment rows carry counts only, never commenter names: the ledger and summary describe the
intake, not the people who wrote the comments.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Iterable

from gather.captions import NO_MATCHING_LANGUAGE, NONE_OFFERED, TRANSLATION_ONLY
from gather.ytdlp import TERMINAL_CODES

SUMMARY_SCHEMA = "gather.video-intake-summary/v1"

# A missing caption for one of these reasons will not change on a retry.
SETTLED_CAPTION_REASONS = frozenset({NONE_OFFERED, TRANSLATION_ONLY, NO_MATCHING_LANGUAGE})

DOES_NOT_PROVE = (
    "that the listing holds every upload: a channel tab omits private, removed, and members-only uploads",
    "that comments are complete: yt-dlp captures what YouTube serves at fetch time",
    "that auto-captions are an accurate transcript of the audio",
)


def pass_name(captions: str, comments: bool) -> str:
    """The pass a run belongs to, from its caption mode and comment flag."""
    if captions == "only":
        return "captions"
    base = "metadata" if captions == "skip" else "full"
    return f"{base}-comments" if comments else base


def needs_captions(pass_: str) -> bool:
    return pass_ == "captions" or pass_.startswith("full")


def intake_dir(store: str) -> str:
    return os.path.join(store, "intake")


def ledger_path(store: str, pass_: str) -> str:
    return os.path.join(intake_dir(store), f"ledger-{pass_}.jsonl")


def append_row(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def latest_rows(path: str) -> dict[str, dict]:
    """The latest ledger row per entry id. A malformed line raises a located ValueError."""
    latest: dict[str, dict] = {}
    if not os.path.exists(path):
        return latest
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"intake ledger line {n} is not valid JSON: {exc}") from exc
            latest[str(row.get("id", ""))] = row
    return latest


def is_settled(row: dict, pass_: str) -> bool:
    """True when a retry of this entry in this pass would not change its outcome."""
    status = row.get("status")
    if status == "failed":
        return row.get("code") in TERMINAL_CODES
    if status != "ok":
        return False
    if not needs_captions(pass_):
        return True
    return row.get("caption") in ("manual", "auto") or row.get("caption_reason") in SETTLED_CAPTION_REASONS


def stored_refs(rows: Iterable[dict], kind: str) -> set[str]:
    """Video ids that already have an item of ``kind`` in the corpus catalog."""
    return {str(r.get("ref", "")) for r in rows if r.get("source") == "video" and r.get("kind") == kind}


def summarize(rows: Iterable[dict]) -> dict:
    """Counts per outcome over ledger rows: statuses, captions (with missing reasons),
    comments, failures by reason, and retries. Pure."""
    rows = list(rows)
    status = Counter(r.get("status", "unknown") for r in rows)
    captions = Counter(r.get("caption", "skipped") for r in rows)
    missing = Counter(r.get("caption_reason") or "unknown" for r in rows if r.get("caption") == "missing")
    failures = Counter(r.get("code") or "error" for r in rows if r.get("status") == "failed")
    by_tab: dict[str, Counter] = {}
    for r in rows:
        by_tab.setdefault(str(r.get("tab", "")), Counter())[r.get("status", "unknown")] += 1
    return {
        "entries": len(rows),
        "status": dict(sorted(status.items())),
        "by_tab": {tab: dict(sorted(c.items())) for tab, c in sorted(by_tab.items())},
        "captions": {
            "manual": captions.get("manual", 0), "auto": captions.get("auto", 0),
            "missing": captions.get("missing", 0), "skipped": captions.get("skipped", 0),
            "missing_by_reason": dict(sorted(missing.items())),
        },
        "comments": {
            "total": sum(int(r.get("comments") or 0) for r in rows),
            "videos_with_comments": sum(1 for r in rows if int(r.get("comments") or 0) > 0),
            "reported_by_youtube": sum(int(r.get("comment_count_reported") or 0) for r in rows),
        },
        "failures_by_reason": dict(sorted(failures.items())),
        "retries": {
            "total": sum(int(r.get("retries") or 0) for r in rows),
            "entries_retried": sum(1 for r in rows if int(r.get("retries") or 0) > 0),
            "throttle_budget_spent": sum(1 for r in rows if r.get("throttled")),
        },
    }


def write_json(path: str, doc: dict) -> None:
    """Write a JSON document atomically (temp file, then rename)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
