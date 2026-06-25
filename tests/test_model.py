import sys

import pytest

from gather.derive import synthesize_item
from gather.item import make_item
from gather.model import SubprocessSynthesizer, build_prompt


def _it(id, text):
    return make_item(kind="document", id=id, title=f"T{id}", text=text,
                     source="web", ref=id, method="http-get", fetched_at=1.0)


def test_build_prompt_includes_instruction_and_bounded_inputs():
    p = build_prompt([_it("a", "alpha body"), _it("b", "beta body")], "summarize", max_chars=4)
    assert p.startswith("summarize")
    assert "Sources:" in p
    assert "alph" in p and "alpha body" not in p   # each input is bounded to max_chars


def test_build_prompt_caps_the_number_of_inputs_and_notes_the_omission():
    p = build_prompt([_it(str(i), f"body{i}") for i in range(10)], "go", max_inputs=3)
    assert "body0" in p and "body2" in p
    assert "body3" not in p                  # beyond the cap
    assert "7 more input(s) omitted" in p    # the omission is stated, never silent


def test_subprocess_synthesizer_requires_a_command():
    with pytest.raises(ValueError):
        SubprocessSynthesizer([])


# a real subprocess that reads stdin and emits a statement, cross-platform via the test interpreter
_ECHO = [sys.executable, "-c", "import sys; sys.stdout.write('INFERRED: ' + sys.stdin.read().split(chr(10))[0])"]


def test_subprocess_synthesizer_runs_the_command_over_stdin():
    synth = SubprocessSynthesizer(_ECHO)
    out = synth.synthesize([_it("a", "alpha")], "the instruction line")
    assert out.startswith("INFERRED: the instruction line")  # prompt reached the process via stdin
    assert synth.method == "synthesized"


def test_synthesize_item_through_the_model_edge_is_a_real_synthesis():
    a, b = _it("a", "alpha"), _it("b", "beta")
    it = synthesize_item(SubprocessSynthesizer(_ECHO), [a, b], "infer", fetched_at=2.0, ref="claim")
    assert it.provenance.method == "synthesized"             # not compiled: a real model produced it
    assert it.provenance.derived_from == (a.provenance.sha256, b.provenance.sha256)
    assert it.verify()                                       # and it is a consistent, receipted item


def test_subprocess_synthesizer_raises_on_empty_output():
    quiet = SubprocessSynthesizer([sys.executable, "-c", "pass"])  # writes nothing
    with pytest.raises(RuntimeError):
        quiet.synthesize([_it("a", "alpha")], "x")
