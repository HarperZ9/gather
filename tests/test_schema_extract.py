"""Schema extraction with per-field provenance, and the hallucination REJECT."""
from __future__ import annotations

from gather.schema_extract import Field, extract_schema, verify_record

_FIXTURE = (
    "<html><head><title>Shop</title></head><body>"
    '<h1 class="name">Widget</h1>'
    '<span class="price">$19.99</span>'
    '<a class="link" href="http://e.com/1">one</a>'
    '<a class="link" href="http://e.com/2">two</a>'
    "</body></html>"
)
_SCHEMA = {
    "name": Field("h1.name"),
    "price": Field("span.price", regex=r"[\d.]+"),
    "links": Field("a.link", attr="href", many=True),
    "sku": Field("div.sku", required=True),
}


def test_schema_extract_record_and_provenance() -> None:
    ex = extract_schema(_FIXTURE, _SCHEMA, "http://e.com/p", fetched_at=1.0)
    rec = ex.record()
    assert rec["name"] == "Widget"
    assert rec["price"] == "19.99"
    assert rec["links"] == ["http://e.com/1", "http://e.com/2"]
    assert rec["sku"] is None
    assert ex.missing_required() == ["sku"]
    assert ex.method == "schema-extract"
    assert ex.verify(_FIXTURE) is True


def test_schema_extract_binds_each_value_to_a_source_node() -> None:
    ex = extract_schema(_FIXTURE, _SCHEMA, "http://e.com/p", fetched_at=1.0)
    name_field = next(f for f in ex.fields if f.name == "name")
    assert name_field.hits[0].path.endswith("h1[1]")
    assert name_field.hits[0].source_sha256  # a real hash of the source node text


def test_tampered_source_fails_verification() -> None:
    ex = extract_schema(_FIXTURE, _SCHEMA, "http://e.com/p", fetched_at=1.0)
    assert ex.verify(_FIXTURE.replace("Widget", "Gadget")) is False


def test_verify_record_accepts_grounded_values() -> None:
    v = verify_record(_FIXTURE, {"name": "Widget", "price": "$19.99"})
    assert v.ok is True
    assert v.rejected == ()


def test_verify_record_rejects_hallucinated_value() -> None:
    v = verify_record(_FIXTURE, {"name": "Widget", "spec": "quantum flux capacitor"})
    assert v.ok is False
    rejected_names = {r.name for r in v.rejected}
    assert rejected_names == {"spec"}          # the fabricated field, not the real one


def test_verify_record_grounds_list_values() -> None:
    v = verify_record(_FIXTURE, {"links": ["one", "two"]})
    assert v.ok is True
    v2 = verify_record(_FIXTURE, {"links": ["one", "three"]})
    assert v2.ok is False
    assert {r.value for r in v2.rejected} == {"three"}
