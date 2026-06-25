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


def test_parse_feed_rejects_malformed_xml():
    with pytest.raises(ValueError):
        parse_feed("<rss><broken", "u", fetched_at=1.0)
