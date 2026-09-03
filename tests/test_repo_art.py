"""The front-page artwork stays true to the words it illustrates.

A picture in a README is never diffed, so it drifts from the text silently:
somebody edits a stage name, nobody re-renders, and the diagram now describes
a version of the tool that no longer exists. Here the picture is a pure
function of a spec that IS diffable, and this re-renders it and compares the
result against what is committed.

The truncation test is the one that earns its place. A stage note is wrapped to
a fixed number of lines and the wrapper drops the rest, so an edited sentence
can lose its ending in the drawing while reading fine in the spec.

The card a spec also carries is drawn by the same renderer and checked in
tests/test_repo_card.py, which measures it against the font files rather than
against the renderer's own idea of how wide its text is.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "docs" / "art"
SCRIPTS = ROOT / "scripts"


def _load(name):
    # repo_flow imports repo_art by bare name, the way the renderer runs it.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load("repo_art")
FLOW = _load("repo_flow")
RENDER = _load("render_repo_art")

SPECS = sorted(ART.glob("*.art.json"))


def test_there_is_at_least_one_spec():
    assert SPECS, "docs/art holds no *.art.json spec"


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.name)
def test_committed_artwork_matches_its_spec(spec_path):
    for path, text in RENDER.rendered(spec_path).items():
        assert path.exists(), f"{path.name} was never rendered"
        assert path.read_text(encoding="utf-8") == text + "\n", (
            f"{path.name} is stale; run python scripts/render_repo_art.py")


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.name)
def test_rendering_twice_gives_the_same_bytes(spec_path):
    """The corona is random draws. Seeded ones, or this fails."""
    assert RENDER.rendered(spec_path) == RENDER.rendered(spec_path)


def test_each_repository_gets_its_own_drawing():
    """The identity claim, checked rather than asserted in a doc."""
    names = ["gather", "flywheel", "crucible", "index", "forum", "telos"]
    marks = {n: R.header_svg(
        {"name": n, "role": "x", "tagline": "y", "words": ["z"]}) for n in names}
    assert len({R.seed_for(n) for n in names}) == len(names)
    bodies = {n: re.sub(r"[A-Z]{3,}", "", svg) for n, svg in marks.items()}
    assert len(set(bodies.values())) == len(names), "two repositories drew alike"


def test_the_seed_is_recorded_on_the_mark():
    """A generated mark carries the seed that made it."""
    svg = R.header_svg({"name": "gather", "role": "x", "tagline": "y",
                        "words": []})
    assert f"SEED {R.seed_for('gather') % 100000:05d}" in svg


def test_no_local_paths_or_em_dashes_in_the_art():
    for path in sorted(ART.glob("*.svg")):
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text, f"{path.name} carries an em-dash"
        assert not re.search(r"[A-Z]:[\/]", text), f"{path.name} names a path"


def _specs():
    return [json.loads(p.read_text(encoding="utf-8")) for p in SPECS]


def test_the_spec_words_reach_the_drawing():
    """Guards against a diagram that renders but silently drops content."""
    for spec_path in SPECS:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        rendered = "".join(RENDER.rendered(spec_path).values())
        assert spec["header"]["tagline"] in rendered
        for flow in spec.get("flows", []):
            for stage in flow["stages"]:
                assert stage["title"] in rendered, stage["title"]


def test_no_card_note_loses_its_ending_to_the_wrapper():
    for spec in _specs():
        for flow in spec.get("flows", []):
            for stage in flow["stages"]:
                note = stage["note"]
                drawn = " ".join(FLOW._wrap(note))
                assert drawn == " ".join(note.split()), (
                    f'{stage["title"]}: the drawing cuts off at "{drawn}"')


def test_a_return_edge_stays_on_its_own_row():
    """A backward edge is routed under the row it leaves, so a cross-row one
    would be drawn straight through whatever cards sit in between."""
    for spec in _specs():
        for flow in spec.get("flows", []):
            for edge in flow.get("returns", []):
                assert edge["from"] // FLOW.PER_ROW == edge["to"] // FLOW.PER_ROW, (
                    f'return {edge["from"]}->{edge["to"]} crosses a row break')


# The widest tagline that has been looked at on a rendered page. It counts
# characters rather than measuring glyphs, so it cannot tell "mmmm" from
# "iiii": a guardrail, not a typographic fact.
TAGLINE_BUDGET = 70


def test_the_tagline_stays_inside_its_rule():
    """The header tagline is drawn on one unwrapped line under the rule. Too
    long and it runs on toward the aperture, with nothing about the render
    failing to say so."""
    for spec in _specs():
        tagline = spec["header"]["tagline"]
        assert len(tagline) <= TAGLINE_BUDGET, (
            f"{len(tagline)} characters runs past the rule: {tagline!r}")


def _outcome_budgets(count):
    """Label and note budgets for one box in a band of `count` boxes. The
    geometry is repo_flow._outcomes: the band spans the page inside the
    margins, split `count` ways with a gap between, and the text starts 14
    in from the left edge of its box."""
    span = (FLOW.W - FLOW.PAD * 2 - FLOW.GAP * (count - 1)) / count
    usable = span - 14 - 10
    return int(usable / 7.0), int(usable / 5.4)


def _outcomes_that_overflow(flow):
    label_budget, note_budget = _outcome_budgets(len(flow["outcomes"]))
    bad = []
    for item in flow["outcomes"]:
        if len(item["label"]) > label_budget:
            bad.append(f'{item["label"]!r} is wider than its box')
        if len(item["note"]) > note_budget:
            bad.append(f'the note under {item["label"]} is wider than its '
                       f'box: {item["note"]!r}')
    return bad


def test_no_outcome_runs_out_of_its_box():
    """An outcome box holds one unwrapped label over one unwrapped note, and
    neither is clipped, so an over-long note runs into the box beside it
    instead of failing anything."""
    for spec in _specs():
        for flow in spec.get("flows", []):
            assert not _outcomes_that_overflow(flow)


def test_that_check_can_actually_fail():
    """A green suite otherwise proves only that the check ran. Widen a note
    past its box and the check has to say so."""
    flow = {"outcomes": [
        {"label": "OK", "note": "x" * 200, "tone": "verified"},
        {"label": "y" * 200, "note": "short", "tone": "drift"},
    ]}
    assert len(_outcomes_that_overflow(flow)) == 2

# Where an illustration lives. `.github/assets/` and `docs/brand/` are
# deliberately outside this set: they hold the 1280x640 social-preview source,
# which is uploaded through the repository settings rather than linked from
# prose. Their presence is covered by tests/test_docs.py.
SHOWN_DIRS = ("docs/art",)


def test_every_illustration_is_actually_shown_to_a_reader():
    """No orphans. An image nobody links to is an image nobody sees."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs = "".join(p.read_text(encoding="utf-8", errors="ignore")
                   for p in ROOT.glob("docs/**/*.md"))
    haystack = readme + docs
    images = sorted(p for d in SHOWN_DIRS for p in (ROOT / d).glob("*")
                    if p.suffix.lower() in {".svg", ".png"})
    orphans = [str(p.relative_to(ROOT)).replace("\\", "/")
               for p in images
               if str(p.relative_to(ROOT)).replace("\\", "/") not in haystack]
    assert not orphans, f"committed but never shown: {orphans}"
