"""The balanced comment synthesis, with false-success controls: a coordinated spam group that must
be flagged, a real critique that must not be set aside as noise (a terse one and a harsh one), a
paper citation that must not read as promotion, and a reply that must stay attached to its parent."""

import json

from gather.comment_balance import balance, excerpt, flatten
from gather.comment_report import balance_item, report_markdown
from gather.comment_signals import classify
from gather.item import make_item

SPAM = [
    ("s1", "I always thought the mind was complicated, but my anxiety was just old programming. My only savior was "
           "to read The Quiet Lantern (Dana Holt), it's a genial book, this should be taught in schools!"),
    ("s2", "Watching this I felt so predetermined. Luckily, I found all the answers in the book called The Quiet "
           "Lantern from Dana Holt. It's genius, my anxiety is gone, my favourite one."),
    ("s3", "This got me thinking about childhood patterns. Luckily, someone told me to read The Quiet Lantern by "
           "Dana Holt, and it totally shifted my perspective."),
]
CRITIQUE = ("c1", "Representing an observer does not explain it. What operations build the self-model, and how "
                  "are actions attributed to it?")
HARSH = ("c2", "This is nonsense because he conflates first-order experience with noticing that you notice, "
               "and the second is rare in daily life.")
REPLY = ("c1.r1", "Exactly, and the clinical cases where actions stop feeling like one's own show that the attribution "
                  "step is real and can fail.")
CITATION = ("p1", "Levin and Fields have a preprint, Cognitive Offloading is a Cognitive Universal, that argues "
                  "the observer is distributed because cells offload memory to the environment.")
SUPPORT = ("u1", "Brilliant conversation, thank you. The idea that the self-model is learned early makes sense of "
                 "infant development.")
ATTACK = ("a1", "Typical grifter, ignore him.")
REACTION = ("r1", "Let's gooo!!")


def comments():
    rows = [*SPAM, CRITIQUE, HARSH, CITATION, SUPPORT, ATTACK, REACTION]
    out = [{"id": i, "parent": "root", "text": t, "like_count": n, "author": f"@person{n}"} for n, (i, t) in enumerate(rows)]
    out.append({"id": REPLY[0], "parent": "c1", "text": REPLY[1], "like_count": 2, "author": "@replier"})
    out.append({"id": "ch1", "parent": "root", "text": "We edited this one with new tools.", "like_count": 9,
                "author": "@TheChannel", "author_is_uploader": True})
    return out


def by_id(rec):
    return {r["id"]: r for r in rec["comments"]}


def test_the_coordinated_promotion_group_is_flagged_with_its_shared_signals():
    rec = balance(comments())
    assert len(rec["coordinated"]) == 1
    g = rec["coordinated"][0]
    assert sorted(g["comments"]) == ["s1", "s2", "s3"]
    assert "product named with its author" in g["shared_signals"]
    assert rec["counts"]["coordinated_spam"] == 3
    assert rec["balance"]["likes_to_promotion"] == 0 + 1 + 2


def test_a_real_critique_is_kept_as_substantive_critique():
    rec = by_id(balance(comments()))
    assert rec["c1"]["category"] == "substantive" and rec["c1"]["stance"] == "critique"


def test_a_harsh_critique_that_gives_a_reason_is_not_set_aside_as_a_dismissal():
    rec = by_id(balance(comments()))
    assert rec["c2"]["category"] == "substantive"
    assert rec["c2"]["stance"] == "critique"


def test_a_paper_citation_is_a_pointer_not_promotion():
    rec = by_id(balance(comments()))
    assert rec["p1"]["category"] == "substantive"
    assert rec["p1"]["pointer"] is True


def test_a_reply_stays_attached_to_its_parent_and_joins_its_claim():
    rec = balance(comments())
    r = by_id(rec)["c1.r1"]
    assert r["parent"] == "c1" and r["thread"] == "c1" and not r["parent_missing"]
    assert r["agrees_with_parent"] is True and r["toward_video"] == "critique"
    claim = next(c for c in rec["claims"] if "c1" in c["comments"])
    assert "c1.r1" in claim["comments"]
    assert claim["replies"] >= 1


def test_attacks_reactions_and_the_channel_are_set_aside_with_a_reason():
    rec = by_id(balance(comments()))
    assert rec["a1"]["category"] == "ad_hominem" and rec["a1"]["evidence"]
    assert rec["r1"]["category"] == "reaction"
    assert rec["ch1"]["category"] == "channel"


def test_every_comment_is_in_exactly_one_category():
    rec = balance(comments())
    ids = [r["id"] for r in rec["comments"]]
    assert sorted(ids) == sorted(c["id"] for c in comments())
    assert sum(rec["counts"][k] for k in ("substantive", "reaction", "ad_hominem", "dismissal", "promotional",
                                          "coordinated_spam", "channel")) == len(ids)


def test_the_balance_counts_both_sides():
    b = balance(comments())["balance"]
    assert b["critique"] == 3  # c1, c2 and the reply that agrees with c1
    assert b["support"] == 1
    assert "Weighted toward critique" in b["sentence"]


def test_no_commenter_is_named_and_every_excerpt_is_under_15_words():
    rec = balance(comments())
    text = json.dumps(rec) + report_markdown(rec)
    assert "@person" not in text and "@replier" not in text and "TheChannel" not in text
    for c in rec["claims"]:
        assert len(c["excerpt"]["text"].replace(" ...", "").split()) < 15
    assert excerpt("@someone " + "word " * 30).split()[0] == "word"


def test_lone_promotion_is_not_called_coordinated():
    rec = balance([{"id": "x", "parent": "root", "text": SPAM[0][1], "like_count": 1}])
    assert rec["counts"]["promotional"] == 1 and rec["counts"]["coordinated_spam"] == 0


def test_a_reply_whose_parent_was_not_read_is_marked():
    rec = balance([{"id": "z.r", "parent": "z", "text": REPLY[1], "like_count": 0}])
    assert rec["comments"][0]["parent_missing"] is True


def test_the_stance_rules_are_symmetric():
    # the same words aimed at either side give the same category
    a = classify("Typical grifter, ignore him.")
    b = classify("Typical grifter, ignore her.")
    assert a.category == b.category == "ad_hominem"


def test_a_thread_tree_flattens_with_parents():
    flat = flatten([{"id": "a", "text": "t", "replies": [{"id": "a.b", "text": "u", "replies": []}]}])
    assert [(c["id"], c["parent"]) for c in flat] == [("a", None), ("a.b", "a")]


def test_the_page_is_a_compiled_item_over_the_comments():
    items = [make_item(kind="comment", id=c["id"], title="c", text=c["text"], source="video", ref="v",
                       method="yt-dlp", fetched_at=0.0) for c in comments()]
    it = balance_item(balance(comments()), items, fetched_at=1.0, ref="v")
    assert it.provenance.method == "compiled"
    assert len(it.provenance.derived_from) == len(items)
    assert it.verify()
