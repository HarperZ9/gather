import dataclasses

from gather.digest import digest, verify_digest
from gather.item import make_item


def _it(id, text):
    return make_item(kind="transcript", id=id, title="T", text=text,
                     source="video", ref=id, method="yt-dlp", fetched_at=1.0)


def test_digest_records_receipts_and_seals_them():
    d = digest([_it("a", "x"), _it("b", "y")])
    assert len(d.receipts) == 2
    assert len(d.seal) == 64
    assert verify_digest(d) is True


def test_seal_is_order_independent():
    d1 = digest([_it("a", "x"), _it("b", "y")])
    d2 = digest([_it("b", "y"), _it("a", "x")])
    assert d1.seal == d2.seal  # depends on what was gathered, not the arrival order


def test_tampered_receipt_breaks_the_seal():
    d = digest([_it("a", "x")])
    bad = dataclasses.replace(d, receipts=({**d.receipts[0], "sha256": "0" * 64},))
    assert verify_digest(bad) is False


def test_swapping_field_values_between_receipts_breaks_the_seal():
    # two distinct items; swapping one's title into the other's ref position must change the seal
    # (the named-key canonicalization binds each value to its field, so no permutation collides)
    a = make_item(kind="document", id="a", title="Alpha", text="x", source="web",
                  ref="ref-a", method="http-get", fetched_at=1.0)
    b = make_item(kind="document", id="b", title="Beta", text="y", source="web",
                  ref="ref-b", method="http-get", fetched_at=1.0)
    base = digest([a, b]).seal
    a2 = make_item(kind="document", id="a", title="ref-a", text="x", source="web",
                   ref="Alpha", method="http-get", fetched_at=1.0)  # title and ref values swapped
    assert digest([a2, b]).seal != base


def test_relabelling_how_an_item_was_obtained_breaks_the_seal():
    # passing a synthesis off as a direct fetch must not pass verification
    d = digest([_it("a", "x")])
    relabeled = dataclasses.replace(d, receipts=({**d.receipts[0], "method": "synthesized"},))
    assert verify_digest(relabeled) is False
    reffed = dataclasses.replace(d, receipts=({**d.receipts[0], "ref": "elsewhere"},))
    assert verify_digest(reffed) is False


def test_retitling_a_receipt_breaks_the_seal():
    # a title is displayed and load-bearing for a reader, so it is sealed too
    d = digest([_it("a", "x")])
    bad = dataclasses.replace(d, receipts=({**d.receipts[0], "title": "Something Else"},))
    assert verify_digest(bad) is False


def test_rewriting_the_derivation_chain_breaks_the_seal():
    it = make_item(kind="paper", id="p1", title="claim", text="derived fact", source="papers",
                   ref="synthesis", method="synthesized", fetched_at=1.0, derived_from=("a", "b"))
    d = digest([it])
    assert verify_digest(d) is True
    assert d.receipts[0]["derived_from"] == ["a", "b"]
    dropped = dataclasses.replace(d, receipts=({**d.receipts[0], "derived_from": ["a"]},))
    assert verify_digest(dropped) is False
    reordered = dataclasses.replace(d, receipts=({**d.receipts[0], "derived_from": ["b", "a"]},))
    assert verify_digest(reordered) is False  # input order is meaningful, so reordering is detected


def test_fetched_at_is_bound_into_the_seal():
    from gather.item import make_item
    a = make_item(kind="webpage", id="x", title="t", text="body",
                  source="web", ref="r", method="http-get", fetched_at=100.0)
    b = make_item(kind="webpage", id="x", title="t", text="body",
                  source="web", ref="r", method="http-get", fetched_at=200.0)
    # same content, different retrieval time -> the seal must differ, so the
    # witnessed retrieval time cannot be edited without breaking the seal
    assert digest([a]).seal != digest([b]).seal
