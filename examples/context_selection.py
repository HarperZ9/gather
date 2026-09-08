"""Offline readable context selection example.

Creates a tiny local corpus, inspects bounded verified excerpts, then selects
one explicit text range into a private context payload. No network or model is
used.
"""
from __future__ import annotations

import json
import pathlib
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from gather import Corpus, inspect_corpus, make_item, select_context


def main() -> int:
    with TemporaryDirectory() as tmp:
        corpus = Corpus(tmp, fsync=False)
        corpus.add([
            make_item(
                kind="document",
                id="source-1",
                title="Decision note",
                text="0123456789DECISION-FACT-ALPHAzz. Extra private source text.",
                source="docs",
                ref="source-1",
                method="file-read",
                fetched_at=1.0,
            )
        ])

        inspected = inspect_corpus(corpus, excerpt_chars=24)
        row_ref = inspected["rows"][0]["row_ref"]
        selected = select_context(
            corpus,
            [{"row_ref": row_ref, "start": 10, "limit": 19}],
            expected_corpus_digest=inspected["corpus_digest"],
        )
        print(json.dumps({"inspect": inspected, "selected": selected}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
