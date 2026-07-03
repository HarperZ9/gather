"""Streaming, partial-update HTML extraction with witnessed increments.

Phil Holden's `partialupdate` (from the talk "What if AI replies in HTML not
Markdown?") parses an HTML stream incrementally and commits only the STABLE part,
holding back the incomplete tail so a progressively-rendered document never
flashes half-open markup. The repo is gone, but the idea is clear and gather is
its natural home: as an AI (or any producer) streams HTML, extract it as it
arrives.

gather adds the accountability layer none of the streaming libraries carry. As
each block element closes it is COMMITTED with a content hash and linked into an
append-only hash chain, so a streamed extraction is a re-verifiable ledger of
stable increments. The still-open tail is explicitly PENDING (not yet
verifiable), never silently treated as final. The boundary between committed and
pending is on the record, the same stable-vs-incomplete honesty extract.py
applies to a whole document, applied here to a live stream.

Determinism: chunk boundaries do not matter. html.parser buffers incomplete tags
across feeds, so feeding a document in any split yields the same commits, hashes,
and order as feeding it whole.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html.parser import HTMLParser

from gather.dom import VOID, Node
from gather.extract import to_markdown
from gather.item import content_hash

# Leaf block-text elements committed the moment their end tag arrives. A closed
# leaf block is final in an append-only stream, so it is safe to witness.
COMMIT_BLOCKS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "blockquote", "pre", "td", "th", "dd", "dt", "figcaption",
}


def _chain(prev: str, core: dict) -> str:
    return hashlib.sha256((prev + json.dumps(core, sort_keys=True)).encode("utf-8")).hexdigest()


def _block_markdown(node: Node) -> str:
    """Render a single block as Markdown. to_markdown renders a node's children,
    so wrap the block in a throwaway root to render the block ITSELF (a heading
    keeps its ``#`` prefix, a list item its marker, etc.)."""
    wrapper = Node("#root")
    wrapper.content.append(node)
    return to_markdown(wrapper)


@dataclass(frozen=True, slots=True)
class Commit:
    """One stable increment: a block that has fully arrived, hashed and chained."""

    seq: int
    path: str
    tag: str
    text: str
    sha256: str
    markdown: str
    entry_hash: str

    def as_dict(self) -> dict:
        return {
            "seq": self.seq, "path": self.path, "tag": self.tag,
            "sha256": self.sha256, "entry_hash": self.entry_hash,
        }


@dataclass(frozen=True, slots=True)
class StreamLedger:
    """Append-only, hash-chained record of the committed increments. Re-derive the
    chain to prove the stream was not reordered, truncated, or edited."""

    commits: tuple[Commit, ...]
    root_hash: str

    def verify(self) -> bool:
        prev = ""
        for c in self.commits:
            core = {"seq": c.seq, "path": c.path, "tag": c.tag, "sha256": c.sha256}
            if _chain(prev, core) != c.entry_hash:
                return False
            prev = c.entry_hash
        return prev == self.root_hash

    def markdown(self) -> str:
        return "\n\n".join(c.markdown for c in self.commits if c.markdown)


class _StreamBuilder(HTMLParser):
    """Incremental tree builder that records a block the instant its end tag
    arrives. Paths match dom.parse_dom (pos assigned at parse time)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self._stack: list[Node] = [self.root]
        self._counts: dict[int, dict[str, int]] = {}
        self._closed: list[Node] = []

    def _make(self, tag, attrs) -> Node:
        parent = self._stack[-1]
        counts = self._counts.setdefault(id(parent), {})
        counts[tag] = counts.get(tag, 0) + 1
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent, pos=counts[tag])
        parent.content.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._make(tag, attrs)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._make(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                closed = self._stack[i]
                del self._stack[i:]
                if tag in COMMIT_BLOCKS:
                    self._closed.append(closed)
                return

    def handle_data(self, data):
        self._stack[-1].content.append(data)

    def take_closed(self) -> list[Node]:
        out, self._closed = self._closed, []
        return out

    def open_tags(self) -> list[str]:
        return [n.tag for n in self._stack[1:]]


class StreamingExtractor:
    """Feed HTML chunks; get stable blocks committed with receipts as they close.

        sx = StreamingExtractor()
        for chunk in chunks:
            for commit in sx.feed(chunk):
                ...          # a block just became stable and is hashed
        sx.close()
        sx.ledger()          # the re-verifiable ledger of stable increments
        sx.pending()         # tags still open (not yet committed / verifiable)
    """

    def __init__(self) -> None:
        self._builder = _StreamBuilder()
        self._seq = 0
        self._prev = ""
        self._commits: list[Commit] = []

    def feed(self, chunk: str) -> list[Commit]:
        self._builder.feed(chunk)
        return self._drain()

    def _drain(self) -> list[Commit]:
        new: list[Commit] = []
        for node in self._builder.take_closed():
            text = node.text_content()
            if not text:
                continue
            self._seq += 1
            core = {"seq": self._seq, "path": node.path, "tag": node.tag,
                    "sha256": content_hash(text)}
            self._prev = _chain(self._prev, core)
            commit = Commit(self._seq, node.path, node.tag, text, content_hash(text),
                            _block_markdown(node), self._prev)
            self._commits.append(commit)
            new.append(commit)
        return new

    def pending(self) -> list[str]:
        """Tags still open in the stream: the incomplete tail, not yet committed
        and not yet verifiable."""
        return self._builder.open_tags()

    def close(self) -> list[Commit]:
        """Flush the parser. Blocks left unclosed at stream end are NOT committed
        (a truncated block is honestly left pending, never witnessed as final)."""
        self._builder.close()
        return self._drain()

    def ledger(self) -> StreamLedger:
        return StreamLedger(tuple(self._commits), self._prev)


def stream_extract(chunks) -> StreamLedger:
    """Convenience: feed an iterable of chunks and return the finished ledger."""
    sx = StreamingExtractor()
    for chunk in chunks:
        sx.feed(chunk)
    sx.close()
    return sx.ledger()
