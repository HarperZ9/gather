import pytest

from gather.derive import NullSynthesizer, Synthesizer, derive, synthesize_item
from gather.item import content_hash, make_item


def _it(id, text):
    return make_item(kind="transcript", id=id, title=f"T{id}", text=text,
                     source="video", ref=id, method="yt-dlp", fetched_at=1.0)


def test_derive_records_inputs_by_content_hash_and_compiles_by_default():
    a, b = _it("a", "alpha"), _it("b", "beta")
    it = derive([a, b], "alpha and beta assembled", fetched_at=2.0, ref="claim-1")
    assert it.provenance.method == "compiled"  # bare derive never claims a synthesis
    assert it.provenance.sha256 == content_hash("alpha and beta assembled")  # the assembly, not inputs
    assert it.provenance.derived_from == (content_hash("alpha"), content_hash("beta"))  # re-checkable pointers
    assert it.verify() is True


def test_derive_refuses_to_label_anything_synthesized():
    # the headline guarantee: "synthesized" is unreachable without the seam, even low-level
    a = _it("a", "alpha")
    with pytest.raises(ValueError, match="synthesize_item"):
        derive([a], "a fabricated claim", fetched_at=1.0, ref="x", method="synthesized")


def test_derive_refuses_empty_inputs():
    with pytest.raises(ValueError):
        derive([], "a statement from nothing", fetched_at=1.0, ref="x")


def test_null_synthesizer_compiles_verbatim_and_labels_it_compiled():
    # the standing default invents nothing: it assembles inputs and labels the result "compiled"
    a, b = _it("a", "alpha"), _it("b", "beta")
    it = synthesize_item(NullSynthesizer(), [a, b], "compare them", fetched_at=2.0, ref="c1")
    assert it.provenance.method == "compiled"            # not "synthesized": no model, no new claim
    assert "alpha" in it.text and "beta" in it.text      # inputs are present verbatim
    assert "compare them" in it.text                     # the prompt is the heading
    assert it.provenance.derived_from == (content_hash("alpha"), content_hash("beta"))
    assert it.verify() is True


def test_null_synthesizer_is_deterministic():
    a, b = _it("a", "alpha"), _it("b", "beta")
    s = NullSynthesizer()
    assert s.synthesize([a, b], "p") == s.synthesize([a, b], "p")


def test_a_model_synthesizer_yields_a_synthesized_item_through_the_seam():
    # a real model edge sets method="synthesized"; the seam stamps the item with it
    class FakeModel:
        method = "synthesized"

        def synthesize(self, inputs, prompt):
            return f"inferred: {prompt}"

    model: Synthesizer = FakeModel()
    a = _it("a", "alpha")
    it = synthesize_item(model, [a], "what follows", fetched_at=3.0, ref="m1")
    assert it.provenance.method == "synthesized"
    assert it.text == "inferred: what follows"
    assert it.provenance.derived_from == (content_hash("alpha"),)
    assert it.verify() is True
