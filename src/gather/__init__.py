"""Gather: an accountable research-intake organ.

The one place network access, third-party tools, and credentials are allowed to live,
isolated behind source adapters, so the rest of the constellation stays clean. Every
ingested item carries a provenance receipt, and a gather run emits a witnessed digest
that index, refine, and the crucible consume. A peer organ: it composes through the
seam, it does not absorb or get absorbed.

The stable surface is re-exported here (``from gather import make_item, Corpus, gather_run``);
adapters and the network/credentials edges are imported from their submodules when needed.
"""

from gather.availability import assess_availability, stored_probe, witness_availability
from gather.derive import NullSynthesizer, Synthesizer, derive, synthesize_item
from gather.digest import Digest, digest, digest_of_receipts, verify_digest
from gather.item import Item, Provenance, content_hash, make_item
from gather.provenance import NullProvenanceProvider, ProvenanceProvider
from gather.recall import Query, recall, recall_audited
from gather.run import RunRecord, gather_run, verify_record
from gather.scope import filter_scope, in_scope
from gather.source import Catalog, Source
from gather.store import Corpus

__version__ = "1.6.1"

__all__ = [
    "Catalog", "Corpus", "Digest", "Item", "NullProvenanceProvider", "NullSynthesizer",
    "Provenance", "ProvenanceProvider", "Query", "RunRecord", "Source", "Synthesizer",
    "assess_availability", "content_hash", "derive", "digest", "digest_of_receipts",
    "filter_scope", "gather_run", "in_scope", "make_item", "recall", "recall_audited",
    "stored_probe", "synthesize_item", "verify_digest", "verify_record",
    "witness_availability", "__version__",
]
