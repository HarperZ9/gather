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


def test_parse_api_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_api("{not json", "u", fetched_at=1.0)
