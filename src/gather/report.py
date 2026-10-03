"""Cited reports written by a local model from fixed excerpts, with every citation checked.

``write_report`` numbers the excerpts, asks the model to answer the question quoting the
excerpts exactly with their numbers (``"exact words" [2]``), then runs ``gather.citecheck`` on
the answer. The report becomes one Item with ``method="synthesized"``, ``derived_from`` set to
the excerpts' content hashes, and the full check result in ``meta["citation_check"]``. An
unverifiable citation is marked in that result, never removed from the text.

The model is a ``LocalModel``: loopback endpoints only, so only a model the user runs on their own
machine writes the report. The method follows the one-pass local report writers described for
AstaBrief; Gather ships no AstaBrief weights, data or outputs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence

from gather.citecheck import check_report
from gather.item import Item, content_hash, make_item
from gather.local_model import LocalModel

REPORT_SCHEMA = "gather.report/1"
MAX_EXCERPT_CHARS = 4000

SYSTEM = (
    "You write short research answers from numbered excerpts and nothing else. Rules: "
    "1. Every sentence that states a fact must contain an exact quotation copied word for word from "
    "one excerpt, in double quotes, followed by that excerpt's number in square brackets, like this: "
    '"exact words from the excerpt" [2]. '
    "2. Quote at least four consecutive words. Do not change, shorten or join the quoted words. "
    "3. Cite only the numbered excerpts. Use no outside knowledge. "
    "4. If the excerpts do not answer the question, write: The excerpts do not answer this question. "
    "5. Write at most five sentences, in plain prose, with no headings."
)


def excerpts_block(excerpts: Sequence[Item], max_chars: int = MAX_EXCERPT_CHARS) -> str:
    return "\n\n".join(f"[{n}] {it.title.strip()}\n{it.text.strip()[:max_chars]}"
                       for n, it in enumerate(excerpts, 1))


def write_report(question: str, excerpts: Sequence[Item], model: LocalModel, *,
                 wall: Callable[[], float] = time.time) -> Item:
    """Ask the local model, check its citations, and return the report Item."""
    if not question.strip():
        raise ValueError("a report needs a question")
    if not excerpts:
        raise ValueError("a report needs at least one excerpt")
    user = f"Question: {question.strip()}\n\nExcerpts:\n\n{excerpts_block(excerpts)}"
    reply = model.chat(SYSTEM, user)
    texts = [it.text.strip()[:MAX_EXCERPT_CHARS] for it in excerpts]
    check = check_report(reply.text, texts)
    meta = {"schema": REPORT_SCHEMA, "question": question.strip(), "model": reply.model,
            "endpoint": "loopback", "elapsed_s": round(reply.elapsed_s, 3), "citation_check": check}
    return make_item(kind="report", id=f"report-{content_hash(question.strip())[:12]}", title=question.strip()[:120],
                     text=reply.text, source="report", ref=question.strip()[:200], method="synthesized",
                     fetched_at=float(wall()),
                     derived_from=tuple(it.provenance.sha256 for it in excerpts), meta=meta)


def load_excerpts(path: str) -> list[Item]:
    """Excerpts from a JSON file: a list of objects with ``text`` and optional ``title``, ``id``
    and ``ref``. Each becomes a direct ``file-read`` Item whose hash the report records."""
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("text"), str) for r in rows):
        raise ValueError("excerpts must be a JSON list of objects with a text field")
    return [make_item(kind="excerpt", id=str(r.get("id", n)), title=str(r.get("title", "")), text=r["text"],
                      source="docs", ref=str(r.get("ref", path)), method="file-read", fetched_at=time.time())
            for n, r in enumerate(rows, 1)]
