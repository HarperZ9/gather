from gather.derive import NullSynthesizer, derive, synthesize_item
from gather.item import make_item
from gather.method import (
    DERIVED,
    DIRECT,
    UNKNOWN,
    consistent,
    directness,
    is_consistent,
)


def _it(text, method, source="web", derived_from=()):
    return make_item(kind="document", id="x", title="X", text=text, source=source,
                     ref="x", method=method, fetched_at=1.0, derived_from=derived_from)


def test_directness_classifies_known_methods():
    assert directness("http-get") == DIRECT
    assert directness("arxiv-api-id") == DIRECT
    assert directness("synthesized") == DERIVED
    assert directness("compiled") == DERIVED
    assert directness("some-new-adapter") == UNKNOWN


def test_consistent_primitive_flags_mismatches():
    assert consistent("http-get", has_derived_from=False) is True
    assert consistent("http-get", has_derived_from=True) is False    # a fetch must not claim inputs
    assert consistent("synthesized", has_derived_from=False) is False  # a synthesis must have inputs
    assert consistent("synthesized", has_derived_from=True) is True
    assert consistent("brand-new-method", has_derived_from=True) is True   # unknown makes no claim


def test_is_consistent_on_real_built_items():
    direct = _it("body", "http-get")                  # direct, no inputs
    assert is_consistent(direct) is True
    a, b = _it("alpha", "http-get"), _it("beta", "http-get")
    compiled = synthesize_item(NullSynthesizer(), [a, b], "p", fetched_at=1.0, ref="c")
    assert directness(compiled.provenance.method) == DERIVED
    assert is_consistent(compiled) is True            # compiled, and it carries derived_from
    assert is_consistent(derive([a], "x", fetched_at=1.0, ref="r")) is True


def test_make_item_allows_an_unknown_method_either_way():
    # an unregistered method is not classified, so it is not rejected with or without inputs
    assert _it("body", "brand-new-method", derived_from=("abc",)).provenance.method == "brand-new-method"
    assert _it("body", "brand-new-method").provenance.method == "brand-new-method"
