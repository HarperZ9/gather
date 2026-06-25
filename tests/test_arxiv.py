import pytest

from gather.arxiv import arxiv_query_url, parse_arxiv

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


def test_arxiv_query_url_distinguishes_an_id_from_a_search():
    assert "id_list=2301.12345" in arxiv_query_url("2301.12345")
    assert "id_list=2301.12345v2" in arxiv_query_url("2301.12345v2")
    u = arxiv_query_url("aperiodic monotile")
    assert "search_query=all" in u and "aperiodic" in u and "id_list" not in u


def test_parse_arxiv_rejects_malformed_xml():
    with pytest.raises(ValueError):
        parse_arxiv("<feed><broken", fetched_at=1.0)
