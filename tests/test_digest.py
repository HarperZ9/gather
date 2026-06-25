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


def test_relabelling_how_an_item_was_obtained_breaks_the_seal():
    # passing a synthesis off as a direct fetch must not pass verification
    d = digest([_it("a", "x")])
    relabeled = dataclasses.replace(d, receipts=({**d.receipts[0], "method": "synthesized"},))
    assert verify_digest(relabeled) is False
    reffed = dataclasses.replace(d, receipts=({**d.receipts[0], "ref": "elsewhere"},))
    assert verify_digest(reffed) is False


def test_rewriting_the_derivation_chain_breaks_the_seal():
    it = make_item(kind="paper", id="p1", title="claim", text="derived fact", source="papers",
                   ref="synthesis", method="synthesized", fetched_at=1.0, derived_from=("a", "b"))
    d = digest([it])
    assert verify_digest(d) is True
    assert d.receipts[0]["derived_from"] == ["a", "b"]
    bad = dataclasses.replace(d, receipts=({**d.receipts[0], "derived_from": ["a"]},))
    assert verify_digest(bad) is False
