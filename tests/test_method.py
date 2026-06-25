from gather.derive import NullSynthesizer, derive, synthesize_item
from gather.item import make_item
from gather.method import DERIVED, DIRECT, UNKNOWN, directness, is_consistent


def _it(text, method, source="web", derived_from=()):
    return make_item(kind="document", id="x", title="X", text=text, source=source,
                     ref="x", method=method, fetched_at=1.0, derived_from=derived_from)


def test_directness_classifies_known_methods():
    assert directness("http-get") == DIRECT
    assert directness("arxiv-api-id") == DIRECT
    assert directness("synthesized") == DERIVED
    assert directness("compiled") == DERIVED
    assert directness("some-new-adapter") == UNKNOWN


def test_a_direct_item_with_no_inputs_is_consistent():
    assert is_consistent(_it("body", "http-get")) is True


def test_a_direct_item_claiming_inputs_is_inconsistent():
    # a fetched item should not carry a derivation chain
    assert is_consistent(_it("body", "http-get", derived_from=("abc",))) is False


def test_real_derived_items_are_consistent():
    a = _it("alpha", "http-get")
    b = _it("beta", "http-get")
    compiled = synthesize_item(NullSynthesizer(), [a, b], "p", fetched_at=1.0, ref="c")
    assert directness(compiled.provenance.method) == DERIVED
    assert is_consistent(compiled) is True            # compiled, and it carries derived_from
    # a derived item with an empty chain would be inconsistent
    empty = derive([a], "x", fetched_at=1.0, ref="r")  # method defaults to compiled, derived_from set
    assert is_consistent(empty) is True


def test_an_unknown_method_makes_no_claim():
    assert is_consistent(_it("body", "brand-new-method", derived_from=("abc",))) is True
