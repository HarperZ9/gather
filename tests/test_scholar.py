"""Tests for the scholarly-graph federation adapter (gather.scholar).

Recorded fixtures, no live network: the three providers describe the SAME paper (the
aperiodic monotile, DOI 10.1234/monotile) in their three native shapes, so DOI dedup,
citation-edge extraction, and provenance-preserving federation are all exercised offline.
A fake fetcher drives ScholarSource end to end without touching urllib.
"""

import json

import pytest

from gather.digest import digest_of_receipts, verify_digest
from gather.method import directness
from gather.scholar import (
    CITATION_METHOD,
    CITATIONS,
    REFERENCES,
    CitationEdge,
    ScholarError,
    ScholarSource,
    citation_edges,
    crossref_url,
    federate,
    normalize_doi,
    openalex_url,
    parse_crossref,
    parse_openalex,
    parse_semanticscholar,
    semanticscholar_url,
    work_to_item,
)

# --- Recorded fixtures: one paper, three graphs -----------------------------

OPENALEX = json.dumps({
    "results": [{
        "id": "https://openalex.org/W100",
        "doi": "https://doi.org/10.1234/MONOTILE",  # mixed case + URL form on purpose
        "title": "An Aperiodic Monotile",
        "publication_year": 2023,
        "authors": None,
        "authorships": [
            {"author": {"display_name": "Author One"}},
            {"author": {"display_name": "Author Two"}},
        ],
        "abstract_inverted_index": {"A": [0], "single": [1], "shape": [2], "tiles": [3]},
        "referenced_works": ["https://openalex.org/W200", "https://openalex.org/W201"],
    }]
})

SEMANTICSCHOLAR = json.dumps({
    "data": [{
        "paperId": "ss-abc",
        "externalIds": {"DOI": "10.1234/monotile"},
        "title": "An Aperiodic Monotile",
        "abstract": "A single shape that tiles the plane aperiodically.",
        "year": 2023,
        "authors": [{"name": "Author One"}, {"name": "Author Two"}],
        "references": [{"paperId": "ss-ref1", "externalIds": {"DOI": "10.9999/prior-tile"}}],
        "citations": [{"paperId": "ss-cite1", "externalIds": {"DOI": "10.5555/follow-up"}}],
    }]
})

CROSSREF = json.dumps({
    "message": {
        "items": [{
            "DOI": "10.1234/monotile",
            "title": ["An Aperiodic Monotile"],
            "issued": {"date-parts": [[2023, 3, 20]]},
            "author": [{"given": "Author", "family": "One"}, {"given": "Author", "family": "Two"}],
            "reference": [{"DOI": "10.9999/prior-tile"}, {"DOI": "10.7777/crossref-only-ref"}],
        }]
    }
})


# --- normalize_doi ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("10.1234/monotile", "10.1234/monotile"),
    ("10.1234/MONOTILE", "10.1234/monotile"),
    ("https://doi.org/10.1234/monotile", "10.1234/monotile"),
    ("http://dx.doi.org/10.1234/Monotile", "10.1234/monotile"),
    ("doi:10.1234/monotile", "10.1234/monotile"),
    ("  10.1234/monotile  ", "10.1234/monotile"),
])
def test_normalize_doi_canonicalizes(raw, expected):
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", ["", "not-a-doi", "10.1234", "monotile", None, 42, "arxiv:2301.12345"])
def test_normalize_doi_rejects_non_dois(raw):
    assert normalize_doi(raw) == ""


# --- per-provider parsers ---------------------------------------------------

def test_parse_openalex_reconstructs_abstract_and_edges():
    works = parse_openalex(OPENALEX)
    assert len(works) == 1
    w = works[0]
    assert w.provider == "openalex" and w.method == "openalex-api"
    assert w.doi == "10.1234/monotile"           # normalized from the URL+mixed-case form
    assert w.key == "10.1234/monotile"           # DOI is the key
    assert w.title == "An Aperiodic Monotile"
    assert w.abstract == "A single shape tiles"  # inverted index reassembled in order
    assert w.authors == ("Author One", "Author Two")
    assert w.year == "2023"
    assert w.references == ("openalex:W200", "openalex:W201")
    assert w.citations == ()                      # OpenAlex list has no incoming citers: honest empty


def test_parse_semanticscholar_extracts_references_and_citations():
    works = parse_semanticscholar(SEMANTICSCHOLAR)
    assert len(works) == 1
    w = works[0]
    assert w.provider == "semanticscholar" and w.method == "semanticscholar-api"
    assert w.doi == "10.1234/monotile" and w.key == "10.1234/monotile"
    assert w.abstract == "A single shape that tiles the plane aperiodically."
    assert w.references == ("10.9999/prior-tile",)   # keyed by DOI when the edge target has one
    assert w.citations == ("10.5555/follow-up",)


def test_parse_crossref_reads_metadata_and_reference_dois():
    works = parse_crossref(CROSSREF)
    assert len(works) == 1
    w = works[0]
    assert w.provider == "crossref" and w.method == "crossref-api"
    assert w.doi == "10.1234/monotile"
    assert w.title == "An Aperiodic Monotile"
    assert w.abstract == ""                          # crossref carries no abstract here: honest
    assert w.year == "2023"
    assert w.authors == ("Author One", "Author Two")
    assert w.references == ("10.9999/prior-tile", "10.7777/crossref-only-ref")


def test_parsers_skip_records_with_no_identity():
    assert parse_openalex(json.dumps({"results": [{"title": "no id no doi"}]})) == []
    assert parse_crossref(json.dumps({"message": {"items": [{"title": ["no doi"]}]}})) == []


def test_parsers_reject_malformed_json():
    for parse in (parse_openalex, parse_semanticscholar, parse_crossref):
        with pytest.raises(ScholarError):
            parse("{not json")


# --- work -> item (a direct paper receipt) ----------------------------------

def test_work_to_item_is_a_direct_paper_receipt():
    w = parse_semanticscholar(SEMANTICSCHOLAR)[0]
    it = work_to_item(w, fetched_at=1.0)
    assert it.kind == "paper" and it.provenance.source == "scholar"
    assert it.provenance.method == "semanticscholar-api"
    assert directness(it.provenance.method) == "direct"       # a fetch, on the ladder
    assert it.provenance.derived_from == ()                   # a direct fetch carries no inputs
    assert it.meta["doi"] == "10.1234/monotile"
    assert it.meta["references"] == ["10.9999/prior-tile"]
    assert it.verify()


def test_crossref_item_text_falls_back_to_title_when_no_abstract():
    w = parse_crossref(CROSSREF)[0]
    it = work_to_item(w, fetched_at=1.0)
    assert it.text == "An Aperiodic Monotile"    # metadata record fingerprints its title, not ""
    assert it.verify()


# --- citation edges as first-class receipts ---------------------------------

def test_citation_edge_receipt_seals_the_link():
    edge = CitationEdge("10.1234/a", "10.1234/b", REFERENCES, "semanticscholar")
    r = edge.receipt()
    assert r["method"] == CITATION_METHOD and r["kind"] == "citation-edge"
    assert r["source"] == "scholar" and r["ref"] == "semanticscholar"
    # editing either endpoint, the direction, or the provider changes the sha256
    flipped = CitationEdge("10.1234/a", "10.1234/c", REFERENCES, "semanticscholar").receipt()
    assert flipped["sha256"] != r["sha256"]
    rev = CitationEdge("10.1234/a", "10.1234/b", CITATIONS, "semanticscholar").receipt()
    assert rev["sha256"] != r["sha256"]


def test_citation_edges_directions_and_dedup():
    works = (parse_openalex(OPENALEX) + parse_semanticscholar(SEMANTICSCHOLAR)
             + parse_crossref(CROSSREF))
    edges = citation_edges(works)
    # references point OUT from the monotile; the SS citation points IN to it
    keyset = {(e["title"], e["ref"]) for e in edges}
    assert ("10.1234/monotile -> 10.9999/prior-tile", "semanticscholar") in keyset
    assert ("10.5555/follow-up -> 10.1234/monotile", "semanticscholar") in keyset
    assert ("10.1234/monotile -> 10.7777/crossref-only-ref", "crossref") in keyset
    # crossref and semanticscholar both assert monotile->prior-tile; kept apart by provider
    prior = [e for e in edges if e["title"] == "10.1234/monotile -> 10.9999/prior-tile"]
    assert {e["ref"] for e in prior} == {"crossref", "semanticscholar"}
    # every edge id is unique (no duplicate receipts within one provider)
    assert len({e["id"] for e in edges}) == len(edges)


def test_edges_fold_into_a_verifiable_digest():
    works = parse_semanticscholar(SEMANTICSCHOLAR)
    edges = citation_edges(works)
    d = digest_of_receipts(edges)
    assert verify_digest(d)
    # tamper with a sealed edge: verify must catch it
    tampered = d.receipts[0] | {"title": "10.1234/monotile -> 10.0000/injected"}
    broken = type(d)(receipts=(tampered,) + d.receipts[1:], seal=d.seal)
    assert not verify_digest(broken)


# --- federation: dedup by DOI, keep every provider's provenance -------------

def test_federate_merges_three_providers_by_doi():
    works = (parse_openalex(OPENALEX) + parse_semanticscholar(SEMANTICSCHOLAR)
             + parse_crossref(CROSSREF))
    fed = federate(works)
    assert len(fed) == 1                              # three records, one DOI, one unified work
    fw = fed[0]
    assert fw.doi == "10.1234/monotile"
    assert fw.providers == ("crossref", "openalex", "semanticscholar")   # all three listed, sorted
    assert len(fw.source_hashes) == 3                 # no provenance dropped: one hash per source
    # abstract came from the richest provider in order; OpenAlex has one, so it wins
    assert fw.abstract == "A single shape tiles"
    assert fw.abstract_provider == "openalex"
    # edges unioned across providers
    assert "10.9999/prior-tile" in fw.references
    assert "10.7777/crossref-only-ref" in fw.references
    assert "openalex:W200" in fw.references
    assert fw.citations == ("10.5555/follow-up",)


def test_federated_item_is_a_derived_compiled_record():
    works = (parse_openalex(OPENALEX) + parse_semanticscholar(SEMANTICSCHOLAR)
             + parse_crossref(CROSSREF))
    it = federate(works)[0].to_item(fetched_at=1.0)
    assert it.provenance.method == "compiled"                 # assembled, not a direct fetch
    assert directness(it.provenance.method) == "derived"
    assert len(it.provenance.derived_from) == 3               # points back at all three sources
    assert it.meta["providers"] == ["crossref", "openalex", "semanticscholar"]
    assert it.verify()


def test_federate_never_joins_by_title_only():
    # two works, same title, DIFFERENT DOIs -> must stay two records (DOI is the only join key)
    a = json.dumps({"results": [{"id": "https://openalex.org/W1", "doi": "10.1/a",
                                 "title": "Same Title", "abstract_inverted_index": {"x": [0]}}]})
    b = json.dumps({"message": {"items": [{"DOI": "10.2/b", "title": ["Same Title"]}]}})
    fed = federate(parse_openalex(a) + parse_crossref(b))
    assert len(fed) == 2


def test_federate_keeps_a_doi_less_work_separate():
    # semanticscholar record with no DOI keeps its provider-prefixed key, never merged
    nodoi = json.dumps({"data": [{"paperId": "ss-x", "title": "No DOI Paper"}]})
    fed = federate(parse_semanticscholar(nodoi))
    assert len(fed) == 1
    assert fed[0].key == "semanticscholar:ss-x" and fed[0].doi == ""


# --- ScholarSource end to end over the fake fetcher (offline) ---------------

def _fake_fetcher(provider, url):
    """Route each provider to its recorded fixture; assert the URL is well-formed per provider."""
    if provider == "openalex":
        assert "api.openalex.org" in url
        return OPENALEX
    if provider == "semanticscholar":
        assert "semanticscholar.org" in url
        return SEMANTICSCHOLAR
    if provider == "crossref":
        assert "api.crossref.org" in url
        return CROSSREF
    raise AssertionError(f"unexpected provider {provider}")


def test_scholarsource_federated_fetch_dedups_and_emits_one_paper():
    src = ScholarSource(fetcher=_fake_fetcher, clock=lambda: 1.0)
    items = src.fetch("10.1234/monotile")
    assert len(items) == 1                              # federated: three graphs, one DOI
    assert items[0].provenance.method == "compiled"
    assert items[0].meta["providers"] == ["crossref", "openalex", "semanticscholar"]
    assert items[0].verify()


def test_scholarsource_unfederated_emits_each_providers_paper():
    src = ScholarSource(fetcher=_fake_fetcher, federated=False, clock=lambda: 1.0)
    items = src.fetch("10.1234/monotile")
    assert len(items) == 3                              # one per provider, undeduped
    assert {i.provenance.method for i in items} == {
        "openalex-api", "semanticscholar-api", "crossref-api"}
    assert all(i.verify() for i in items)


def test_scholarsource_graph_returns_papers_and_edges():
    src = ScholarSource(fetcher=_fake_fetcher, clock=lambda: 1.0)
    items, edges = src.graph("10.1234/monotile")
    assert len(items) == 1 and len(edges) >= 3
    d = digest_of_receipts(
        [{"kind": i.kind, "id": i.id, "title": i.title, "source": i.provenance.source,
          "ref": i.provenance.ref, "method": i.provenance.method, "sha256": i.provenance.sha256,
          "derived_from": list(i.provenance.derived_from)} for i in items]
        + edges
    )
    assert verify_digest(d)                             # one seal over papers AND edges


def test_scholarsource_subset_of_providers():
    src = ScholarSource(providers=("crossref",), fetcher=_fake_fetcher, clock=lambda: 1.0,
                        federated=False)
    items = src.fetch("10.1234/monotile")
    assert len(items) == 1 and items[0].provenance.method == "crossref-api"


def test_scholarsource_rejects_unknown_provider():
    with pytest.raises(ScholarError):
        ScholarSource(providers=("scopus",))
    with pytest.raises(ScholarError):
        ScholarSource(providers=())


# --- query URLs are pure and injection-safe ---------------------------------

def test_query_urls_route_doi_vs_search_and_encode():
    assert "filter=doi%3A10.1234%2Fmonotile" in openalex_url("10.1234/monotile")
    assert "search=" in openalex_url("aperiodic tiling")
    # a DOI lookup path-encodes the slash so it cannot break the crossref path
    assert crossref_url("10.1234/monotile").endswith("/10.1234%2Fmonotile")
    assert "query=" in crossref_url("aperiodic tiling")
    u = semanticscholar_url("tiling & groups")
    assert "%26" in u and "references" in u and "citations" in u
