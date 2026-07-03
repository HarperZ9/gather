"""Scholarly-graph federation: OpenAlex, Semantic Scholar, and Crossref into one intake.

Three of the open scholarly graphs answer the same question in three different shapes.
OpenAlex, Semantic Scholar, and Crossref each describe a paper, and each carries a slice
of the citation graph around it (the works it references, the works that cite it). This
adapter unifies the three into gather's intake so a research corpus can draw on all of
them at once, with two properties the accountability layer needs:

  - **Citation edges are first-class provenance.** A reference or a citation is not just
    a number on a record; it is an edge with an origin. ``citation_edges`` turns each edge
    into its own re-checkable receipt (method ``citation-edge``), fingerprinting the exact
    ``from -> to`` link and which provider asserted it, so an edge folded into a witnessed
    digest cannot be edited, grafted on, or stripped off without breaking the seal. An edge
    is a claim the provider made, sealed as such, never presented as a fact gather verified.

  - **Dedup by DOI, no provenance dropped.** The same paper surfaces from all three graphs.
    ``federate`` joins works on their normalized DOI into one unified record, but keeps every
    provider's receipt (the ``derived_from`` list carries each source work's content hash),
    the same discipline as the corpus store: bodies deduped, receipts never. A work with no
    DOI is its own record; a DOI is the only join key, never a fuzzy title match.

The pure parsers (``parse_openalex``, ``parse_semanticscholar``, ``parse_crossref``) take a
raw API response and no network; ``ScholarSource`` is the isolated impure edge, and its
fetcher is injectable so the whole federation is tested offline over recorded fixtures. The
core stays standard library: json and urllib only.

Honest reach note: an abstract is what these APIs return, not the full paper. OpenAlex and
Semantic Scholar carry abstracts (OpenAlex as an inverted index, reconstructed here);
Crossref usually carries only metadata, so a Crossref work's text is its title and metadata,
labelled by its method, never dressed up as the paper. The unified record's abstract is the
first provider that supplied one, and which provider it came from is on the record.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gather.item import Item, content_hash, make_item
from gather.net import decode_body, http_get

OPENALEX_API = "https://api.openalex.org/works"
SEMANTICSCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_API = "https://api.crossref.org/works"

# The method ladder labels for the three scholarly graphs. Each is a DIRECT fetch of paper
# metadata (registered in gather.method); a citation edge is DIRECT too (the provider stated
# the link, gather records that it did). See gather.method.DIRECT_METHODS.
OPENALEX_METHOD = "openalex-api"
SEMANTICSCHOLAR_METHOD = "semanticscholar-api"
CROSSREF_METHOD = "crossref-api"
CITATION_METHOD = "citation-edge"

# The closed provider vocabulary: which scholarly graph a work or edge came from.
PROVIDERS = ("openalex", "semanticscholar", "crossref")

# The two edge directions. A reference points OUT (this work cites the target); a citation
# points IN (the target cites this work). Both are recorded from the perspective of the work
# the provider returned, so a reader always knows which end is the subject.
REFERENCES = "references"   # from = this work, to = a work it cites
CITATIONS = "citations"     # from = a work that cites this, to = this work


class ScholarError(ValueError):
    """A scholarly-graph input that violates the contract: a typed, diagnosable rejection."""


def normalize_doi(raw: object) -> str:
    """Normalize a DOI to its bare lowercase form, the federation join key. Pure.

    A DOI arrives in several dresses: a bare ``10.1234/xyz``, a ``doi:10.1234/xyz`` prefix, or
    a full ``https://doi.org/10.1234/XYZ`` URL, and DOIs are case-insensitive. This strips the
    URL and ``doi:`` prefixes and lowercases, so the same paper from three providers resolves to
    one key. A value that does not contain a ``10.`` DOI stem returns ``""`` (no key), because a
    junk string must never join two unrelated works. Whitespace is stripped.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().lower()
    if not s:
        return ""
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.strip("/").strip()
    # a real DOI is "10.<registrant>/<suffix>"; anything without that stem is not a DOI key
    if not s.startswith("10.") or "/" not in s:
        return ""
    return s


@dataclass(frozen=True, slots=True)
class CitationEdge:
    """One directed edge in the citation graph, as one provider asserted it.

    ``from_key`` and ``to_key`` are normalized DOIs (or a provider-native id when no DOI is
    known, prefixed by the provider so keys never collide across graphs). ``direction`` is
    ``references`` or ``citations``. ``provider`` records which graph asserted the edge, so a
    reader can weigh it and a later reader can re-check it against that provider. The edge
    witnesses a CLAIM, never a verified fact.
    """

    from_key: str
    to_key: str
    direction: str
    provider: str

    def receipt(self) -> dict:
        """A digest receipt for this edge. The sha256 fingerprints the canonical edge tuple,
        so editing either endpoint, the direction, or the asserting provider in a sealed digest
        breaks ``verify_digest``. The method is ``citation-edge``: this witnesses that the
        provider asserted the link, not that the cited work exists or says what is claimed."""
        canon = json.dumps(
            {"from": self.from_key, "to": self.to_key,
             "direction": self.direction, "provider": self.provider},
            sort_keys=True, ensure_ascii=False,
        )
        edge_id = f"{self.provider}:{self.direction}:{self.from_key}->{self.to_key}"
        return {
            "kind": "citation-edge", "id": edge_id,
            "title": f"{self.from_key} -> {self.to_key}",
            "source": "scholar", "ref": self.provider, "method": CITATION_METHOD,
            "sha256": content_hash(canon), "derived_from": [],
        }


@dataclass(frozen=True, slots=True)
class ScholarWork:
    """One normalized paper record from one scholarly graph, provider-neutral.

    The parsers project each provider's shape onto this one, so federation and edge extraction
    never touch a provider's raw JSON. ``doi`` is normalized (the join key, ``""`` if none);
    ``key`` is the stable identity used in edges (the DOI, or a provider-prefixed native id).
    ``references`` and ``citations`` are the directed edges the provider carried around this
    work. ``provider`` and ``method`` record the origin for the receipt.
    """

    provider: str
    method: str
    key: str
    doi: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    year: str
    native_id: str
    references: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def edges(self) -> list[CitationEdge]:
        """Every citation edge around this work, as directed CitationEdge records.

        A reference is ``self -> target``; a citation is ``target -> self``. Self-loops and
        empty endpoints are dropped (a paper does not cite itself in these graphs, and an edge
        needs both ends), so the edge set is clean before it is sealed.
        """
        out: list[CitationEdge] = []
        for target in self.references:
            if target and target != self.key:
                out.append(CitationEdge(self.key, target, REFERENCES, self.provider))
        for citer in self.citations:
            if citer and citer != self.key:
                out.append(CitationEdge(citer, self.key, CITATIONS, self.provider))
        return out


def _clean(s: object) -> str:
    return " ".join(str(s).split()) if isinstance(s, str) else ""


def _dict(value: object) -> dict:
    """``value`` when it is a dict, else an empty dict: a typed narrowing for provider JSON
    whose nested objects may be absent or the wrong shape from an untrusted API."""
    return value if isinstance(value, dict) else {}


def _work_key(doi: str, provider: str, native_id: str) -> str:
    """The stable identity for a work in the citation graph: its DOI when it has one, else a
    provider-prefixed native id so two providers' ids never collide (an ``openalex:W123`` is
    never confused with a ``semanticscholar:abc``). A work with neither has no key (``""``)."""
    if doi:
        return doi
    if native_id:
        return f"{provider}:{native_id}"
    return ""


# --- OpenAlex ---------------------------------------------------------------

def _openalex_abstract(inv: object) -> str:
    """Reconstruct an abstract from OpenAlex's inverted index (a {word: [positions]} map).

    OpenAlex ships abstracts as an inverted index, not plain text. This inverts it back: place
    each word at each of its positions, then read left to right. A malformed entry (non-int
    position, non-list value) is skipped rather than raising, so one bad token never sinks the
    record. An absent index yields ``""`` (no abstract), never a fabricated one.
    """
    if not isinstance(inv, dict) or not inv:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inv.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and not isinstance(pos, bool):
                slots[pos] = word
    if not slots:
        return ""
    return " ".join(slots[i] for i in sorted(slots))


def _openalex_work(rec: dict) -> ScholarWork | None:
    if not isinstance(rec, dict):
        return None
    native_id = _clean(rec.get("id")).rsplit("/", 1)[-1]  # https://openalex.org/W123 -> W123
    doi = normalize_doi(rec.get("doi"))
    key = _work_key(doi, "openalex", native_id)
    if not key:
        return None
    title = _clean(rec.get("title") or rec.get("display_name"))
    abstract = _openalex_abstract(rec.get("abstract_inverted_index"))
    authors: list[str] = []
    for auth in rec.get("authorships", []) if isinstance(rec.get("authorships"), list) else []:
        if isinstance(auth, dict) and isinstance(auth.get("author"), dict):
            name = _clean(auth["author"].get("display_name"))
            if name:
                authors.append(name)
    year = str(rec["publication_year"]) if isinstance(rec.get("publication_year"), int) else ""
    refs: list[str] = []
    for ref in rec.get("referenced_works", []) if isinstance(rec.get("referenced_works"), list) else []:
        rid = _clean(ref).rsplit("/", 1)[-1]
        if rid:
            refs.append(f"openalex:{rid}")
    meta: dict[str, Any] = {}
    if doi:
        meta["doi"] = doi
    return ScholarWork(
        provider="openalex", method=OPENALEX_METHOD, key=key, doi=doi, title=title,
        abstract=abstract, authors=tuple(authors), year=year, native_id=native_id,
        references=tuple(refs), citations=(), meta=meta,
    )


def parse_openalex(payload: str | bytes) -> list[ScholarWork]:
    """Parse an OpenAlex ``/works`` response into normalized works. Pure: no network.

    Accepts the search shape (``{"results": [...]}``) or a single work object. The abstract is
    reconstructed from OpenAlex's inverted index; referenced works become outgoing edges keyed
    by their OpenAlex id (OpenAlex does not carry per-work incoming citers in the list response,
    so citations stay empty here, honestly). A record with no usable identity is skipped. Raises
    ScholarError on malformed JSON.
    """
    data = _load(payload)
    recs = data.get("results") if isinstance(data, dict) else None
    if recs is None:
        recs = [data] if isinstance(data, dict) else data
    works: list[ScholarWork] = []
    for rec in recs if isinstance(recs, list) else []:
        w = _openalex_work(rec)
        if w is not None:
            works.append(w)
    return works


# --- Semantic Scholar -------------------------------------------------------

def _semanticscholar_work(rec: dict) -> ScholarWork | None:
    if not isinstance(rec, dict):
        return None
    native_id = _clean(rec.get("paperId"))
    ext = _dict(rec.get("externalIds"))
    doi = normalize_doi(ext.get("DOI"))
    key = _work_key(doi, "semanticscholar", native_id)
    if not key:
        return None
    title = _clean(rec.get("title"))
    abstract = _clean(rec.get("abstract"))
    authors = tuple(
        _clean(a.get("name")) for a in rec.get("authors", [])
        if isinstance(a, dict) and _clean(a.get("name"))
    ) if isinstance(rec.get("authors"), list) else ()
    year = str(rec["year"]) if isinstance(rec.get("year"), int) else ""
    refs = _ss_edge_keys(rec.get("references"))
    cites = _ss_edge_keys(rec.get("citations"))
    meta: dict[str, Any] = {}
    if doi:
        meta["doi"] = doi
    return ScholarWork(
        provider="semanticscholar", method=SEMANTICSCHOLAR_METHOD, key=key, doi=doi,
        title=title, abstract=abstract, authors=authors, year=year, native_id=native_id,
        references=refs, citations=cites, meta=meta,
    )


def _ss_edge_keys(raw: object) -> tuple[str, ...]:
    """Keys for a Semantic Scholar reference/citation list: each entry's DOI when present, else
    its paperId prefixed by the provider, so an edge always has a stable, collision-free end."""
    keys: list[str] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        ext = _dict(entry.get("externalIds"))
        doi = normalize_doi(ext.get("DOI"))
        pid = _clean(entry.get("paperId"))
        key = doi or (f"semanticscholar:{pid}" if pid else "")
        if key:
            keys.append(key)
    return tuple(keys)


def parse_semanticscholar(payload: str | bytes) -> list[ScholarWork]:
    """Parse a Semantic Scholar response into normalized works. Pure: no network.

    Accepts the search shape (``{"data": [...]}``) or a single paper object. References and
    citations both arrive on the record and become outgoing and incoming edges keyed by DOI (or
    the provider paperId when no DOI is known). A record with no usable identity is skipped.
    Raises ScholarError on malformed JSON.
    """
    data = _load(payload)
    recs = data.get("data") if isinstance(data, dict) else None
    if recs is None:
        recs = [data] if isinstance(data, dict) else data
    works: list[ScholarWork] = []
    for rec in recs if isinstance(recs, list) else []:
        w = _semanticscholar_work(rec)
        if w is not None:
            works.append(w)
    return works


# --- Crossref ---------------------------------------------------------------

def _crossref_work(rec: dict) -> ScholarWork | None:
    if not isinstance(rec, dict):
        return None
    doi = normalize_doi(rec.get("DOI"))
    key = _work_key(doi, "crossref", "")
    if not key:
        return None
    title = ""
    if isinstance(rec.get("title"), list) and rec["title"]:
        title = _clean(rec["title"][0])
    abstract = _clean(rec.get("abstract"))  # crossref abstracts are JATS XML when present; often absent
    authors: list[str] = []
    for a in rec.get("author", []) if isinstance(rec.get("author"), list) else []:
        if isinstance(a, dict):
            name = _clean(f"{a.get('given', '')} {a.get('family', '')}")
            if name:
                authors.append(name)
    year = _crossref_year(rec)
    refs: list[str] = []
    for ref in rec.get("reference", []) if isinstance(rec.get("reference"), list) else []:
        if isinstance(ref, dict):
            rdoi = normalize_doi(ref.get("DOI"))
            if rdoi:
                refs.append(rdoi)
    meta: dict[str, Any] = {"doi": doi}
    return ScholarWork(
        provider="crossref", method=CROSSREF_METHOD, key=key, doi=doi, title=title,
        abstract=abstract, authors=tuple(authors), year=year, native_id="",
        references=tuple(refs), citations=(), meta=meta,
    )


def _crossref_year(rec: dict) -> str:
    issued = rec.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            first = parts[0][0]
            if isinstance(first, int) and not isinstance(first, bool):
                return str(first)
    return ""


def parse_crossref(payload: str | bytes) -> list[ScholarWork]:
    """Parse a Crossref ``/works`` response into normalized works. Pure: no network.

    Accepts the query shape (``{"message": {"items": [...]}}``), a single-work message
    (``{"message": {...}}``), or a bare work. Crossref carries metadata and a reference list
    (outgoing edges by DOI) but no incoming citers, so citations stay empty, honestly. The text
    is usually just title and metadata: Crossref rarely ships an abstract, and the method says
    so. A record with no DOI is skipped (a Crossref work without a DOI has no identity). Raises
    ScholarError on malformed JSON.
    """
    data = _load(payload)
    recs: object = data
    if isinstance(data, dict) and "message" in data:
        msg = data["message"]
        if isinstance(msg, dict) and isinstance(msg.get("items"), list):
            recs = msg["items"]
        else:
            recs = [msg]
    elif isinstance(data, dict):
        recs = [data]
    works: list[ScholarWork] = []
    for rec in recs if isinstance(recs, list) else []:
        w = _crossref_work(rec)
        if w is not None:
            works.append(w)
    return works


# --- Provider dispatch ------------------------------------------------------

_PARSERS: dict[str, Callable[[str | bytes], list[ScholarWork]]] = {
    "openalex": parse_openalex,
    "semanticscholar": parse_semanticscholar,
    "crossref": parse_crossref,
}


def _load(payload: str | bytes) -> object:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScholarError(f"not valid scholarly-graph JSON: {exc}") from exc


# --- Work -> Item -----------------------------------------------------------

def work_to_item(work: ScholarWork, *, fetched_at: float) -> Item:
    """Turn one normalized work into a gather Item with a provenance receipt.

    The text is the abstract when the provider supplied one, else the title (so a Crossref
    metadata record fingerprints its title, not an empty string, and the method records that it
    is metadata, not the paper). ``source`` is ``scholar``, ``ref`` is the work's key (its DOI
    or provider id), and ``method`` is the provider's api label, a DIRECT fetch on the ladder.
    DOI, provider, native id, authors, year, and the edge lists ride in ``meta`` for downstream
    joins. The receipt's sha256 fingerprints the text, re-checkable as ever.
    """
    text = work.abstract or work.title
    meta: dict[str, Any] = {
        "provider": work.provider,
        "doi": work.doi,
        "native_id": work.native_id,
        "authors": list(work.authors),
        "year": work.year,
        "references": list(work.references),
        "citations": list(work.citations),
    }
    meta.update(work.meta)
    return make_item(
        kind="paper", id=work.key, title=work.title, text=text,
        source="scholar", ref=work.key, method=work.method,
        fetched_at=fetched_at, meta=meta,
    )


def citation_edges(works: list[ScholarWork]) -> list[dict]:
    """Every citation edge across a set of works, as digest receipts, de-duplicated.

    Two providers may assert the same edge; identical (from, to, direction, provider) receipts
    collapse to one (the same edge from the same provider is one claim, not two). Edges that
    differ only by provider are kept apart, so the record shows WHO asserted each link. The
    result is a list of receipt dicts ready to fold into a witnessed digest alongside the paper
    items, so an edge is sealed exactly as a paper receipt is.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for work in works:
        for edge in work.edges():
            r = edge.receipt()
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out


# --- Federation: dedup by DOI, keep every receipt ---------------------------

@dataclass(frozen=True, slots=True)
class FederatedWork:
    """One paper unified across providers, joined on its normalized DOI.

    ``doi`` is the join key. ``providers`` names every graph that supplied this paper (sorted,
    deduplicated), and ``source_hashes`` carries each source work's content hash, so no
    provenance is dropped when three records collapse to one: the unified record points back at
    every input, the same discipline as the corpus store. ``title``/``abstract`` are the first
    non-empty values in provider order, and ``abstract_provider`` records which graph the
    abstract came from, so the reader knows its origin. All edges from all providers are unioned.
    """

    doi: str
    key: str
    title: str
    abstract: str
    abstract_provider: str
    authors: tuple[str, ...]
    year: str
    providers: tuple[str, ...]
    references: tuple[str, ...]
    citations: tuple[str, ...]
    source_hashes: tuple[str, ...]

    def to_item(self, *, fetched_at: float) -> Item:
        """The unified paper as a DERIVED gather Item.

        A federated record is not a direct fetch: it is assembled from several providers' records,
        so it carries ``method="compiled"`` and ``derived_from`` set to every source work's content
        hash, exactly the derive-seam discipline. The receipt fingerprints the unified text, and the
        chain back to each provider's contribution stays re-checkable. Which provider each field came
        from rides in ``meta``, so the assembly is never mistaken for one provider's direct claim.
        """
        text = self.abstract or self.title
        meta: dict[str, Any] = {
            "doi": self.doi,
            "providers": list(self.providers),
            "abstract_provider": self.abstract_provider,
            "authors": list(self.authors),
            "year": self.year,
            "references": list(self.references),
            "citations": list(self.citations),
        }
        return make_item(
            kind="paper", id=self.key, title=self.title, text=text,
            source="scholar", ref=self.key, method="compiled",
            fetched_at=fetched_at, derived_from=tuple(self.source_hashes), meta=meta,
        )


def federate(works: list[ScholarWork]) -> list[FederatedWork]:
    """Join works across providers by normalized DOI into unified records. Pure and order-stable.

    Works sharing a DOI collapse to one FederatedWork; a work with no DOI stays its own record
    keyed by its provider id (it cannot be joined, and must never be joined by title). Within a
    group, ``title`` and ``abstract`` take the first non-empty value in provider order (OpenAlex,
    Semantic Scholar, Crossref), so the richest source wins deterministically; ``abstract_provider``
    records which one supplied the abstract. Every provider is listed, every source content hash is
    kept (no provenance dropped), and all providers' edges are unioned with order preserved. The
    join key is the DOI and only the DOI: a title or author overlap never merges two works.
    """
    groups: dict[str, list[ScholarWork]] = {}
    order: list[str] = []
    for w in works:
        gkey = w.doi if w.doi else f"__nodoi__:{w.key}"
        if gkey not in groups:
            groups[gkey] = []
            order.append(gkey)
        groups[gkey].append(w)

    out: list[FederatedWork] = []
    for gkey in order:
        group = sorted(groups[gkey], key=lambda w: PROVIDERS.index(w.provider)
                       if w.provider in PROVIDERS else len(PROVIDERS))
        doi = group[0].doi
        key = doi if doi else group[0].key
        title = _first(group, lambda w: w.title)
        abstract, abstract_provider = _first_with_provider(group, lambda w: w.abstract)
        authors = _first_tuple(group, lambda w: w.authors)
        year = _first(group, lambda w: w.year)
        providers = tuple(sorted({w.provider for w in group}))
        references = _union(group, lambda w: w.references)
        citations = _union(group, lambda w: w.citations)
        source_hashes = tuple(content_hash(w.abstract or w.title) for w in group)
        out.append(FederatedWork(
            doi=doi, key=key, title=title, abstract=abstract,
            abstract_provider=abstract_provider, authors=authors, year=year,
            providers=providers, references=references, citations=citations,
            source_hashes=source_hashes,
        ))
    return out


def _first(group: list[ScholarWork], get: Callable[[ScholarWork], str]) -> str:
    for w in group:
        v = get(w)
        if v:
            return v
    return ""


def _first_with_provider(group: list[ScholarWork], get: Callable[[ScholarWork], str]) -> tuple[str, str]:
    for w in group:
        v = get(w)
        if v:
            return v, w.provider
    return "", ""


def _first_tuple(group: list[ScholarWork], get: Callable[[ScholarWork], tuple[str, ...]]) -> tuple[str, ...]:
    for w in group:
        v = get(w)
        if v:
            return v
    return ()


def _union(group: list[ScholarWork], get: Callable[[ScholarWork], tuple[str, ...]]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for w in group:
        for x in get(w):
            if x and x not in seen:
                seen.add(x)
                out.append(x)
    return tuple(out)


# --- Query URLs (pure) ------------------------------------------------------

def openalex_url(target: str) -> str:
    """The OpenAlex URL for a target: a DOI filter when target is a DOI, else a full-text search.
    Every value is urlencoded, so a query cannot break out of the query string. Pure."""
    doi = normalize_doi(target)
    if doi:
        params = {"filter": f"doi:{doi}"}
    else:
        params = {"search": target.strip()}
    return f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"


def semanticscholar_url(target: str, *, fields: str = "title,abstract,year,authors,externalIds,references,citations") -> str:
    """The Semantic Scholar search URL for a target, requesting the reference and citation lists.
    Every value is urlencoded. Pure."""
    return f"{SEMANTICSCHOLAR_API}?{urllib.parse.urlencode({'query': target.strip(), 'fields': fields})}"


def crossref_url(target: str) -> str:
    """The Crossref URL for a target: a direct work lookup when target is a DOI, else a query.
    A DOI is path-encoded so a slash cannot break the path; a query is urlencoded. Pure."""
    doi = normalize_doi(target)
    if doi:
        return f"{CROSSREF_API}/{urllib.parse.quote(doi, safe='')}"
    return f"{CROSSREF_API}?{urllib.parse.urlencode({'query': target.strip()})}"


_URLS: dict[str, Callable[[str], str]] = {
    "openalex": openalex_url,
    "semanticscholar": semanticscholar_url,
    "crossref": crossref_url,
}


# --- The isolated impure edge -----------------------------------------------

Fetcher = Callable[[str], "str | bytes"]


def _http_fetcher(timeout: float) -> Fetcher:
    def fetch(url: str) -> str:
        body, ctype = http_get(url, timeout=timeout)
        return decode_body(body, ctype)
    return fetch


class ScholarSource:
    """Scholarly-graph federation intake: OpenAlex + Semantic Scholar + Crossref in one adapter.

    The isolated impure edge. ``fetch(target)`` takes a DOI or a free-text query, asks each
    configured provider, parses the responses with the pure parsers, and returns items. With
    ``federated=True`` (the default) it emits one unified paper per DOI (a DERIVED ``compiled``
    item whose ``derived_from`` points at every provider's contribution) plus every citation
    edge as a first-class receipt; with ``federated=False`` it emits each provider's paper
    directly, undeduped. Either way the edges come back so a run seals the graph, not just the
    nodes.

    The network is a seam: the default fetcher is ``gather.net.http_get``, but an injected
    ``fetcher`` (target-provider-url in, response text out) drives the whole federation offline
    over recorded fixtures, so tests need no live network. The provider set is configurable, so a
    caller may run one graph or all three.
    """

    name = "scholar"

    def __init__(
        self,
        *,
        providers: tuple[str, ...] = PROVIDERS,
        federated: bool = True,
        fetcher: Callable[[str, str], "str | bytes"] | None = None,
        clock: Callable[[], float] = time.time,
        timeout: float = 20.0,
    ) -> None:
        bad = [p for p in providers if p not in PROVIDERS]
        if bad:
            raise ScholarError(f"unknown provider(s) {bad}: the vocabulary is {list(PROVIDERS)}")
        if not providers:
            raise ScholarError("at least one provider is required")
        self._providers = tuple(providers)
        self._federated = federated
        self._fetcher = fetcher
        self._clock = clock
        self._timeout = timeout

    def _fetch_provider(self, provider: str, target: str) -> str | bytes:
        url = _URLS[provider](target)
        if self._fetcher is not None:
            return self._fetcher(provider, url)
        return _http_fetcher(self._timeout)(url)

    def works(self, target: str) -> list[ScholarWork]:
        """Every normalized work from every configured provider for a target. Pure given the
        fetcher; this is the federation's raw graph before dedup and item construction."""
        works: list[ScholarWork] = []
        for provider in self._providers:
            payload = self._fetch_provider(provider, target)
            works.extend(_PARSERS[provider](payload))
        return works

    def fetch(self, target: str) -> list[Item]:
        now = float(self._clock())
        works = self.works(target)
        if self._federated:
            items = [fw.to_item(fetched_at=now) for fw in federate(works)]
        else:
            items = [work_to_item(w, fetched_at=now) for w in works]
        return items

    def graph(self, target: str) -> tuple[list[Item], list[dict]]:
        """Fetch and return ``(items, edge_receipts)``: the paper items and the citation edges
        as digest receipts. A caller that wants the edges sealed into the run digest folds both
        lists together; ``fetch`` returns only the items for the plain Source shape."""
        now = float(self._clock())
        works = self.works(target)
        if self._federated:
            items = [fw.to_item(fetched_at=now) for fw in federate(works)]
        else:
            items = [work_to_item(w, fetched_at=now) for w in works]
        return items, citation_edges(works)
