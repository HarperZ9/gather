import pytest

from gather.arxiv import arxiv_query_url, is_arxiv_id, parse_arxiv

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<title>ArXiv Query</title>
<entry>
  <id>http://arxiv.org/abs/2301.12345v2</id>
  <published>2023-01-29T00:00:00Z</published>
  <title>An Aperiodic Monotile</title>
  <summary>  We present a single shape that tiles
  the plane aperiodically.  </summary>
  <author><name>Author One</name></author>
  <author><name>Author Two</name></author>
  <arxiv:doi>10.1234/xyz</arxiv:doi>
  <link href="http://arxiv.org/abs/2301.12345v2" rel="alternate" type="text/html"/>
  <link title="pdf" href="http://arxiv.org/pdf/2301.12345v2" rel="related" type="application/pdf"/>
  <arxiv:primary_category term="math.CO"/>
  <category term="math.CO"/>
  <category term="cs.CG"/>
</entry>
</feed>"""


def test_parse_arxiv_extracts_paper_fields():
    items = parse_arxiv(ARXIV_XML, fetched_at=1.0)
    assert len(items) == 1
    p = items[0]
    assert p.kind == "paper" and p.id == "2301.12345v2"
    assert p.title == "An Aperiodic Monotile"
    assert p.text == "We present a single shape that tiles the plane aperiodically."  # whitespace collapsed
    assert p.provenance.source == "arxiv" and p.provenance.method == "arxiv-api"
    assert p.meta["authors"] == ["Author One", "Author Two"]
    assert p.meta["primary_category"] == "math.CO"
    assert p.meta["categories"] == ["math.CO", "cs.CG"]
    assert p.meta["pdf"] == "http://arxiv.org/pdf/2301.12345v2"   # in meta, the text stays the abstract
    assert p.meta["doi"] == "10.1234/xyz"
    assert p.verify()


@pytest.mark.parametrize("target", [
    "2301.12345",       # new-style 5-digit
    "2301.12345v2",     # versioned
    "0704.0001",        # earliest new-style, 4-digit sequence
    "1501.00001",       # post-2015 5-digit
    "math.CO/0601001",  # old-style with subclass
    "hep-th/9901001",   # old-style, no subclass
    "cs.AI/0601001",
    "  2301.12345  ",   # surrounding whitespace tolerated
])
def test_is_arxiv_id_accepts_real_ids(target):
    assert is_arxiv_id(target) is True


@pytest.mark.parametrize("target", [
    "aperiodic monotile",   # plain query
    "2301.123456",          # 6-digit sequence is not a current arXiv id
    "tiling",
    "group theory survey",
    "",
])
def test_is_arxiv_id_rejects_queries(target):
    assert is_arxiv_id(target) is False


def test_arxiv_query_url_routes_id_vs_search_and_urlencodes():
    assert "id_list=2301.12345" in arxiv_query_url("2301.12345")
    assert "id_list=hep-th%2F9901001" in arxiv_query_url("hep-th/9901001")  # slash encoded, no injection
    u = arxiv_query_url("tiling & groups")
    assert "search_query=all" in u and "id_list" not in u
    assert "%26" in u  # the literal & is percent-encoded, it cannot start a new query param


def test_parse_arxiv_rejects_malformed_xml():
    with pytest.raises(ValueError):
        parse_arxiv("<feed><broken", fetched_at=1.0)
