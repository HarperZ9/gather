"""Pin the XML parsers' safety contract so a future parser swap (e.g. lxml) cannot silently
reintroduce XXE or an entity-expansion blowup. The feed and arxiv adapters both parse untrusted
XML via xml.etree, which does not resolve external entities and caps internal expansion."""

import pytest

from gather.arxiv import parse_arxiv
from gather.feed import parse_feed

_XXE = """<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss version="2.0"><channel><title>F</title>
<item><title>&xxe;</title><link>http://x/1</link></item>
</channel></rss>"""

_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
 <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
 <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
 <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<rss version="2.0"><channel><title>&lol9;</title></channel></rss>"""


def test_feed_does_not_resolve_an_external_entity():
    # the external entity must never expand to the file's contents; etree leaves it undefined
    try:
        items = parse_feed(_XXE, "u", fetched_at=1.0)
    except ValueError:
        return  # undefined entity -> ParseError -> ValueError: the safe outcome
    for it in items:
        assert "root:" not in it.text and "/bin/" not in it.text  # no file content leaked in


def test_arxiv_does_not_resolve_an_external_entity():
    atom = ('<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&xxe;</title>'
            '<id>http://arxiv.org/abs/1</id></entry></feed>')
    try:
        items = parse_arxiv(atom, fetched_at=1.0)
    except ValueError:
        return
    for it in items:
        assert "root:" not in it.text


def test_feed_billion_laughs_does_not_blow_up():
    # the bundled expat caps entity amplification; the parse fails fast as a clean ValueError
    with pytest.raises(ValueError):
        parse_feed(_BILLION_LAUGHS, "u", fetched_at=1.0)
