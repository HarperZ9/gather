"""Every citation must quote its excerpt: answers with an unquoted citation are asked again."""
import json

import pytest

from gather.item import make_item
from gather.local_model import LocalModel
from gather.report import QUOTE_RETRIES, SYSTEM, write_report


def excerpt(n, text):
    return make_item(kind="excerpt", id=str(n), title=f"E{n}", text=text, source="docs", ref="x",
                     method="file-read", fetched_at=0.0)


EXCERPTS = [excerpt(1, "Every run writes a receipt you can re-check later."),
            excerpt(2, "Gather stops at bot checks and records the reason.")]
QUOTED = 'Gather says "every run writes a receipt" [1].'
BARE = "Gather keeps receipts [1]. It also stops at bot checks [2]."


class Tick:
    t = 0.0

    def __call__(self):
        self.t += 2.0
        return self.t


def scripted(*answers):
    """A model that gives the answers in order and records every request."""
    calls = []

    def post(url, body, timeout):
        calls.append(json.loads(body))
        text = answers[min(len(calls), len(answers)) - 1]
        return json.dumps({"model": "m", "choices": [{"message": {"content": text}}]}).encode()
    return LocalModel("m", post=post, clock=Tick()), calls


def test_the_prompt_forbids_a_bracketed_number_without_a_quote():
    assert "A bracketed number with no quotation right before it is not allowed." in SYSTEM
    assert QUOTE_RETRIES == 2


def test_an_unquoted_answer_is_asked_again_and_the_quoted_answer_is_kept():
    model, calls = scripted(BARE, QUOTED)
    item = write_report("What does Gather record?", EXCERPTS, model)
    assert len(calls) == 2 and item.text == QUOTED
    assert item.meta["quote_requirement"] == "met"
    assert item.meta["attempts"] == [{"elapsed_s": 2.0, "unchecked": 2}, {"elapsed_s": 2.0, "unchecked": 0}]
    assert item.meta["elapsed_s"] == 4.0
    assert item.meta["citation_check"]["counts"]["verified"] == 1
    retry = calls[1]["messages"]
    assert retry[0]["content"] == SYSTEM
    assert retry[1]["content"].startswith(calls[0]["messages"][1]["content"])
    assert f"Your previous answer:\n{BARE}" in retry[1]["content"]
    assert "- Gather keeps receipts [1].\n- It also stops at bot checks [2]." in retry[1]["content"]


def test_retries_stop_at_the_cap_and_the_last_answer_is_kept_unchanged():
    last = 'It writes "every run writes a receipt" [1] and more [2].'
    model, calls = scripted(BARE, BARE, last, QUOTED)
    item = write_report("q", EXCERPTS, model)
    assert len(calls) == 1 + QUOTE_RETRIES
    assert item.text == last
    assert item.meta["quote_requirement"] == "unmet"
    check = item.meta["citation_check"]
    assert check["counts"]["unchecked"] == 1 and check["counts"]["verified"] == 1
    assert check["total"] == 2 and check["precision"] == 0.5


@pytest.mark.parametrize("answer", [
    QUOTED,
    'Gather "invents facts out of nothing at all" [1].',
    'Gather "keeps receipts" [1].',
    "The excerpts do not answer this question.",
])
def test_only_an_unquoted_citation_triggers_a_new_answer(answer):
    model, calls = scripted(answer, QUOTED)
    item = write_report("q", EXCERPTS, model)
    assert len(calls) == 1 and item.text == answer
    assert item.meta["quote_requirement"] == "met"


def test_zero_retries_makes_one_call_and_marks_the_requirement_unmet():
    model, calls = scripted(BARE, QUOTED)
    item = write_report("q", EXCERPTS, model, quote_retries=0)
    assert len(calls) == 1 and item.text == BARE
    assert item.meta["quote_requirement"] == "unmet" and item.meta["quote_retries"] == 0
    with pytest.raises(ValueError):
        write_report("q", EXCERPTS, model, quote_retries=-1)


def _cli(monkeypatch, tmp_path, *answers):
    import gather.local_model as lm
    model, calls = scripted(*answers)
    monkeypatch.setattr(lm, "LocalModel", lambda *a, **k: model)
    ex = tmp_path / "ex.json"
    ex.write_text(json.dumps([{"text": e.text} for e in EXCERPTS]), encoding="utf-8")
    return str(ex), calls


def test_gather_report_regenerates_by_default(monkeypatch, tmp_path, capsys):
    from gather.cli import main
    ex, calls = _cli(monkeypatch, tmp_path, BARE, QUOTED)
    assert main(["report", "q", "--excerpts", ex, "--model", "m"]) == 0
    assert len(calls) == 2
    assert "quote requirement: met after 2 model call(s)" in capsys.readouterr().out


def test_gather_report_quote_retries_flag(monkeypatch, tmp_path, capsys):
    from gather.cli import main
    ex, calls = _cli(monkeypatch, tmp_path, BARE, QUOTED)
    assert main(["report", "q", "--excerpts", ex, "--model", "m", "--quote-retries", "0"]) == 1
    assert len(calls) == 1
    with pytest.raises(SystemExit) as exc:
        main(["report", "q", "--excerpts", ex, "--model", "m", "--quote-retries", "-1"])
    assert exc.value.code == 2
