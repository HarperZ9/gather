from gather.web import html_to_title_text, parse_web

HTML = """<html><head><title>My &amp; Page</title><style>.x{color:red}</style></head>
<body><script>var x=1;</script>
<h1>Heading</h1><p>First para.</p><p>Second &lt;para&gt;.</p>
<ul><li>one</li><li>two</li></ul></body></html>"""


def test_html_to_title_text_extracts_title_and_drops_script_and_style():
    title, text = html_to_title_text(HTML)
    assert title == "My & Page"                       # entity decoded, whitespace collapsed
    assert "color:red" not in text and "var x=1" not in text  # style and script dropped
    assert "Heading" in text and "First para." in text
    assert "Second <para>." in text                   # entities in body decoded
    assert "one" in text and "two" in text


def test_html_block_elements_become_line_breaks():
    title, text = html_to_title_text(HTML)
    lines = text.splitlines()
    assert "Heading" in lines and "First para." in lines  # not run together on one line


def test_parse_web_builds_a_receipted_webpage_item():
    it = parse_web(HTML, "https://example.com/p", fetched_at=1.0)
    assert it.kind == "webpage" and it.provenance.source == "web"
    assert it.provenance.method == "http-get"          # a raw fetch, honestly labelled (no JS run)
    assert it.provenance.ref == "https://example.com/p"
    assert it.title == "My & Page"
    assert it.verify() is True
