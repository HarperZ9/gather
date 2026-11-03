"""Per-comment signals for the balanced comment synthesis (``gather.comment_balance``).

Each comment gets one category and the evidence for it: ``substantive`` (an argument, a question
or a pointer about the topic), ``reaction`` (short, no argument), ``ad_hominem`` (an attack on a
person, or on a person's associations, with no argument), ``dismissal`` (rejects the work with no
argument), ``promotional`` (testimony that points to a product), and ``channel`` (the uploader's
own comment). Substantive comments also get a stance toward the video: ``critique``, ``support``
or ``neutral``.

The rules are lexical and deterministic, and stance-neutral: the same words count the same way
whoever they are aimed at. An argument marker always wins over an insult, so a harsh critique that
gives a reason stays substantive. Pure: no network, no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

URL = re.compile(r"https?://\S+|www\.\S+", re.I)
MENTION = re.compile(r"(?<!\w)@[\w.\-]+")
WORD = re.compile(r"[a-z][a-z'\-]*")

STOPWORDS = frozenset("""
a an the and or but if then than so to of in on at by for with from into onto about as is are was were be been being am
do does did done doing have has had having it its it's this that these those there here he she him her his hers they them
their theirs we us our you your yours i me my mine what which who whom whose when where why how not no nor just only also
very really more most much many some any all each every both few other such own same can could would should will shall may
might must let lets let's get got gets like one two way thing things something anything nothing everything even still yet
because however therefore thus though although while whereas since until up down out over under again further once too
s t don doesn didn isn aren wasn weren won wouldn couldn shouldn can't don't doesn't isn't i'm i've i'd you're he's she's
that's what's there's they're we're it'll gonna wanna yeah oh ok okay lol video talk guy guys
""".split())

# An argument: a reason, a contrast, a definition, a test, a mechanism.
ARGUMENT = re.compile(
    r"\b(because|therefore|thus|hence|so that|which means|implies|if\b.{1,60}\bthen|however|but\b|whereas|although|"
    r"explain\w*|distinguish\w*|define\w*|definition|argu\w+|evidence|assum\w+|claim\w*|mechanism|predict\w*|"
    r"test\w*|falsif\w+|counter\w*|conflat\w+|confus\w+|differen\w+|operation\w*|model\w*|hypothes\w+)\b", re.I)

CRITIQUE = re.compile(
    r"\b(however|disagree\w*|wrong|mistak\w+|flaw\w*|fails?\b|failed|misses|problem with|the problem|"
    r"not convinc\w+|unconvinc\w+|doesn'?t (explain|follow|address|answer|work)|does not (explain|follow|address|answer)|"
    r"not the same|isn'?t (true|right|how)|conflat\w+|circular|begs the question|unfalsifiable|no evidence|"
    r"category error|overstat\w+|hand-?wav\w+|ignores?|skeptic\w*|sceptic\w*|doubt\w*|objection\w*|opposite)\b", re.I)

SUPPORT = re.compile(
    r"\b(agree\w*|great|brilliant|love[ds]?|loving|fantastic|thank\w*|excellent|insightful|best|amazing|awesome|"
    r"exactly|well said|spot on|makes sense|wonderful|superb|enjoy\w*|fascinating|mind.?blow\w*|right on|beautiful\w*|"
    r"inspir\w+|incredible|favou?rite|genius|legend\w*|good (one|point|interview|episode|talk|conversation)|so good|"
    r"more of this|keep (it|them) coming|fair point|nailed it)\b", re.I)

INSULT = re.compile(
    r"\b(grifter\w*|charlatan\w*|fraud\w*|clown\w*|idiot\w*|moron\w*|stupid|dumb|quack\w*|huckster\w*|con ?man|"
    r"snake ?oil|creep\w*|pseudo-?intellectual\w*|hack\b|loser\w*|imbecile\w*|delusional|narcissis\w+|crank\w*|"
    r"is a joke|bullshitter\w*)\b", re.I)

DISMISS = re.compile(r"\b(nonsense|pseudoscien\w+|word salad|gibberish|garbage|rubbish|drivel|bs\b|bullshit|waste of time|meaningless|babble)\b", re.I)

# An attack on a person's associations instead of their claim (circumstantial ad hominem).
ASSOCIATION = re.compile(r"\b(epstein|associat\w+ with|friends? with|funded by|ties to|paid by|shill\w*)\b", re.I)

PERSON = re.compile(r"\b(he|him|his|she|her|they|them|this guy|the guest|the host|you|your)\b", re.I)

# Promotion: testimony, a product named with its author, praise for the product, a call to act.
PROMO_SIGNALS: dict[str, re.Pattern[str]] = {
    "product named with its author": re.compile(
        r"\b(book|novel|guide|course|program|app|channel)\b[^.!?\n]{0,40}\b(called|titled|named|by|from)\b\s+[A-Z]"
        r"|\bread(ing)?\s+(the\s+)?[A-Z][\w']+(\s+[A-Z][\w']+){1,5}\s*(\(|,?\s*by\b|\s+from\b)\s*[A-Z]\w+\s+[A-Z]\w+", re.S),
    "personal testimony": re.compile(
        r"\b(changed my life|my (only )?savio(u)?r|my (anxiety|depression|stress)\b|i (finally )?found (all )?the answers|"
        r"luckily,? (i|someone)|i feel (such|so much)|so much more energy|i was stuck|i used to (feel|get) (so|stuck)|"
        r"shifted my perspective|helped me (break|get) free)\b", re.I),
    "praise for the product": re.compile(
        r"\b(genius|genial|must.read|should be taught in schools|nobody talks about|secret info|life.?changing|"
        r"my favou?rite one|eye.?opening read)\b", re.I),
    "call to action": re.compile(r"\b(check out|look up|dm me|message me|whatsapp|telegram|link in (my )?bio|sign up)\b", re.I),
}


@dataclass(slots=True)
class Signals:
    """What the rules saw in one comment."""

    category: str
    stance: str = "neutral"
    evidence: list[str] = field(default_factory=list)
    promo: list[str] = field(default_factory=list)
    words: int = 0
    question: bool = False
    pointer: bool = False


def tokens(text: str) -> list[str]:
    """Content words, lower case, with links, mentions and stopwords removed."""
    plain = MENTION.sub(" ", URL.sub(" ", text or "")).lower()
    return [w.strip("'-") for w in WORD.findall(plain) if len(w) > 2 and w.strip("'-") not in STOPWORDS]


def promo_signals(text: str) -> list[str]:
    """The promotion signals a comment carries, by name."""
    return [name for name, rx in PROMO_SIGNALS.items() if rx.search(text or "")]


def _stance(text: str) -> tuple[str, list[str]]:
    c = [m.group(0).lower() for m in CRITIQUE.finditer(text)]
    s = [m.group(0).lower() for m in SUPPORT.finditer(text)]
    if len(c) > len(s):
        return "critique", c[:4]
    if len(s) > len(c):
        return "support", s[:4]
    return ("mixed", (c + s)[:4]) if c else ("neutral", [])


def classify(text: str, *, from_channel: bool = False) -> Signals:
    """One comment's category, stance and evidence. Pure and deterministic."""
    raw = text or ""
    words = len(MENTION.sub(" ", URL.sub(" ", raw)).split())
    question = "?" in raw
    pointer = bool(URL.search(raw)) or bool(re.search(r"\b(paper|preprint|study|see also|read)\b", raw, re.I))
    if from_channel:
        return Signals("channel", words=words, question=question, pointer=pointer, evidence=["the uploader's own comment"])
    promo = promo_signals(raw)
    if len(promo) >= 2:
        return Signals("promotional", words=words, promo=promo, evidence=promo)
    argued = bool(ARGUMENT.search(raw)) and words >= 8
    insult, dismiss, assoc = INSULT.search(raw), DISMISS.search(raw), ASSOCIATION.search(raw)
    person = PERSON.search(raw)
    if not argued and (insult or assoc) and (person or words < 25):
        hit = (insult or assoc).group(0).lower()  # type: ignore[union-attr]
        return Signals("ad_hominem", words=words, evidence=[f"about the person: {hit}"])
    if not argued and dismiss and words < 30:
        return Signals("dismissal", words=words, evidence=[f"rejects without a reason: {dismiss.group(0).lower()}"])
    if argued or words >= 15 or (question and words >= 6) or (pointer and words >= 6):
        stance, ev = _stance(raw)
        return Signals("substantive", stance=stance, evidence=ev, words=words, question=question, pointer=pointer)
    return Signals("reaction", words=words, question=question, evidence=["short, with no argument"])


# A reply that opens by agreeing ("Exactly, ...", "Agreed.") sides with the comment it answers.
AGREE_OPEN = re.compile(r"^\W*(exactly|agreed?|yes|yep|true|right|indeed|well said|spot on|this\W*$|100%)\b", re.I)
