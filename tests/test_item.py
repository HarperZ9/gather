import dataclasses

from gather.item import content_hash, make_item


def test_make_item_computes_a_verifiable_receipt():
    it = make_item(kind="transcript", id="v1", title="T", text="hello",
                   source="video", ref="v1", method="yt-dlp", fetched_at=1.0)
    assert it.provenance.sha256 == content_hash("hello")
    assert it.verify() is True
    assert it.provenance.source == "video" and it.provenance.method == "yt-dlp"


def test_tampered_item_fails_verify():
    it = make_item(kind="transcript", id="v1", title="T", text="hello",
                   source="video", ref="v1", method="yt-dlp", fetched_at=1.0)
    swapped = dataclasses.replace(it, text="HELLO")  # body changed, receipt unchanged
    assert swapped.verify() is False


def test_synthesized_without_inputs_is_rejected():
    # the method ladder is enforced: a synthesis from nothing is not representable
    import pytest
    with pytest.raises(ValueError, match="derived_from"):
        make_item(kind="paper", id="p1", title="claim", text="derived fact",
                  source="synthesis", ref="r", method="synthesized", fetched_at=2.0)


def test_direct_method_with_inputs_is_rejected():
    # a fetched item cannot claim a derivation chain
    import pytest
    with pytest.raises(ValueError, match="derived_from"):
        make_item(kind="transcript", id="v1", title="T", text="hello", source="video",
                  ref="v1", method="yt-dlp", fetched_at=1.0, derived_from=("abc",))


def test_derived_item_records_the_inputs_it_was_built_from():
    # the hash fingerprints the inference itself; derived_from carries the chain back to sources
    it = make_item(kind="paper", id="p1", title="claim", text="a synthesized fact",
                   source="synthesis", ref="claim-1", method="synthesized", fetched_at=2.0,
                   derived_from=("frag-a", "frag-b"))
    assert it.provenance.derived_from == ("frag-a", "frag-b")
    assert it.provenance.sha256 == content_hash("a synthesized fact")  # the inference, not the inputs
    assert it.verify() is True
