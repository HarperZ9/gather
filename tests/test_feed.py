import pytest

from gather.feed import parse_feed

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>My Blog</title><link>https://blog.example</link>
<item><title>Post One</title><link>https://blog.example/1</link>
<description>about tilings</description><guid>https://blog.example/1</guid>
<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate></item>
<item><title>Post Two</title><link>https://blog.example/2</link>
<description>about groups</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>My Atom</title>
<entry><title>Entry A</title>
<link href="https://a.example/wrong" rel="edit"/>
<link href="https://a.example/a" rel="alternate"/>
<id>tag:a</id><summary>summary a</summary><updated>2026-01-01T00:00:00Z</updated></entry>
</feed>"""


def test_parse_feed_handles_rss():
    items = parse_feed(RSS, "https://blog.example/feed", fetched_at=1.0)
    assert [i.title for i in items] == ["Post One", "Post Two"]
    assert items[0].provenance.ref == "https://blog.example/1"
    assert items[0].text == "about tilings"
    assert items[0].kind == "feed-entry" and items[0].provenance.source == "feed"
    assert items[0].meta.get("feed") == "My Blog"
    assert items[0].meta.get("date") == "Mon, 01 Jan 2026 00:00:00 GMT"
    assert all(i.verify() for i in items)


def test_parse_feed_handles_atom_and_prefers_alternate_link():
    items = parse_feed(ATOM, "https://a.example/feed", fetched_at=1.0)
    assert len(items) == 1
    e = items[0]
    assert e.title == "Entry A"
    assert e.provenance.ref == "https://a.example/a"   # the alternate href, not the edit link or text
    assert e.text == "summary a"
    assert e.id == "tag:a"
    assert e.meta.get("feed") == "My Atom"


def test_parse_feed_does_not_double_count_nested_entries():
    # an entry nested inside an Atom <source> is metadata, not a post, and must not be emitted
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Agg</title>
<entry><title>Real</title><id>r1</id>
<source><title>Origin</title><entry><title>Ghost</title><id>g1</id></entry></source>
</entry></feed>"""
    assert [i.title for i in parse_feed(atom, "u", fetched_at=1.0)] == ["Real"]


def test_parse_feed_handles_rss_1_0_rdf_items_at_root():
    rdf = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
<channel><title>RDF Feed</title></channel>
<item><title>RDF Item</title><link>http://x/1</link></item>
</rdf:RDF>"""
    # in RSS 1.0 the item is a direct child of the root, not under channel
    assert [i.title for i in parse_feed(rdf, "u", fetched_at=1.0)] == ["RDF Item"]


def test_parse_feed_strips_html_in_atom_content():
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>E</title><id>e</id>
<content type="html">&lt;p&gt;hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</content></entry>
</feed>"""
    assert parse_feed(atom, "u", fetched_at=1.0)[0].text == "hello world"  # tags stripped, not left raw


def test_parse_feed_accepts_bytes_with_encoding_declaration():
    # a real feed begins with an XML encoding declaration; parsing a decoded str would raise,
    # so feeds are parsed from bytes and ElementTree honors the declared encoding
    rss = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
           '<title>B</title><item><title>Caf\u00e9</title><link>http://x/1</link></item>'
           '</channel></rss>').encode("utf-8")
    assert parse_feed(rss, "u", fetched_at=1.0)[0].title == "Caf\u00e9"


def test_parse_feed_skips_an_entry_with_no_identity():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>
<item><description>a body but no title, link, or guid</description></item>
<item><title>Real</title><link>http://x/1</link></item>
</channel></rss>"""
    assert [i.title for i in parse_feed(rss, "u", fetched_at=1.0)] == ["Real"]  # the identity-less entry is skipped


def test_parse_feed_rejects_malformed_xml():
    with pytest.raises(ValueError):
        parse_feed("<rss><broken", "u", fetched_at=1.0)
