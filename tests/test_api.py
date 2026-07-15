import json

import pytest

from gather.api import parse_api


def test_parse_api_top_level_list_one_item_per_record():
    payload = json.dumps([{"id": "1", "title": "First", "body": "alpha"},
                          {"id": "2", "title": "Second", "body": "beta"}])
    items = parse_api(payload, "https://api.example/x", fetched_at=1.0)
    assert [i.id for i in items] == ["1", "2"]
    assert items[0].provenance.source == "api" and items[0].provenance.method == "api-get"
    assert items[0].provenance.ref == "https://api.example/x"
    assert all(i.verify() for i in items)


def test_parse_api_items_key_and_text_key():
    payload = json.dumps({"results": [{"id": "p1", "title": "T", "abstract": "the text"}]})
    items = parse_api(payload, "u", fetched_at=1.0, items_key="results", text_key="abstract")
    assert len(items) == 1
    assert items[0].text == "the text"        # text taken from the named field
    assert items[0].title == "T"


def test_parse_api_single_object_becomes_one_item():
    items = parse_api(json.dumps({"id": "only", "v": 1}), "u", fetched_at=1.0)
    assert len(items) == 1 and items[0].id == "only"


def test_parse_api_never_contains_a_credential():
    # the payload and url carry no token; the receipt records only the url (auth is a header)
    items = parse_api(json.dumps([{"id": "1", "title": "x"}]), "https://api.example/data", fetched_at=1.0)
    assert "token" not in items[0].text.lower()
    assert items[0].provenance.ref == "https://api.example/data"


def test_parse_api_serializes_a_non_string_text_field_as_json():
    payload = json.dumps([{"id": "1", "body": {"nested": True}}])
    items = parse_api(payload, "u", fetched_at=1.0, text_key="body")
    assert items[0].text == '{"nested": true}'   # canonical JSON, not a Python repr like {'nested': True}
    assert items[0].verify()


def test_parse_api_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_api("{not json", "u", fetched_at=1.0)


def test_apisource_sends_the_token_in_a_header_and_never_leaks_it(monkeypatch, capsys):
    import gather.api as api_mod
    from gather.api import ApiSource

    monkeypatch.setenv("GATHER_API_TOKEN", "supersecret-xyz")

    def fake_http_get(url, *, timeout=20.0, headers=None, **kw):
        assert headers and headers.get("Authorization") == "Bearer supersecret-xyz"  # token rides the header
        assert "supersecret" not in url                                              # never in the URL
        return b'[{"id":"1","title":"t","v":2}]', "application/json", url

    monkeypatch.setattr(api_mod, "http_get", fake_http_get)
    items = ApiSource().fetch("https://api.example/data")
    captured = capsys.readouterr()
    for i in items:
        assert "supersecret" not in i.text
        assert "supersecret" not in i.provenance.ref
        assert "supersecret" not in i.provenance.method
    assert "supersecret" not in captured.out and "supersecret" not in captured.err


def test_apisource_refuses_a_token_in_the_url(monkeypatch):
    from gather.api import ApiSource
    monkeypatch.setenv("GATHER_API_TOKEN", "supersecret-xyz")
    with pytest.raises(ValueError, match="must not appear in the URL"):
        ApiSource().fetch("https://api.example/data?key=supersecret-xyz")


def test_parse_api_names_dropped_non_object_records(capsys):
    # a mixed array must not silently shrink: the non-object elements dropped
    # are named so the count is not quietly wrong
    payload = json.dumps([{"id": "1"}, "a note", 42, {"id": "2"}])
    items = parse_api(payload, "https://api.example/x", fetched_at=1.0)
    assert len(items) == 2
    err = capsys.readouterr().err
    assert "2" in err and "non-object" in err.lower()


def test_parse_api_all_objects_warns_nothing(capsys):
    parse_api(json.dumps([{"id": "1"}, {"id": "2"}]), "u", fetched_at=1.0)
    assert "non-object" not in capsys.readouterr().err.lower()
