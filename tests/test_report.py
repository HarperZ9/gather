"""Local cited reports: loopback-only model, synthesized receipt, citation check in meta."""
import json

import pytest

from gather.item import make_item
from gather.local_model import LocalModel, require_loopback
from gather.report import load_excerpts, write_report


def excerpt(n, text):
    return make_item(kind="excerpt", id=str(n), title=f"E{n}", text=text, source="docs", ref="x",
                     method="file-read", fetched_at=0.0)


EXCERPTS = [excerpt(1, "Every run writes a receipt you can re-check."), excerpt(2, "Gather stops at bot checks.")]


def fake_post(answer, model="qwen3:8b"):
    calls = []

    def post(url, body, timeout):
        calls.append({"url": url, "body": json.loads(body)})
        return json.dumps({"model": model, "choices": [{"message": {"content": answer}}]}).encode()
    return post, calls


class Tick:
    t = 0.0

    def __call__(self):
        self.t += 2.0
        return self.t


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:11434/v1", "http://localhost:8080/v1", "http://[::1]:8000/v1"])
def test_loopback_endpoints_are_accepted(endpoint):
    assert require_loopback(endpoint) == endpoint


@pytest.mark.parametrize("endpoint", ["https://api.openai.com/v1", "http://10.0.0.5:11434/v1",
                                      "http://127.0.0.1.example.com/v1", "file:///tmp/x", "http://0.0.0.0:1/v1"])
def test_other_endpoints_are_refused_before_any_request(endpoint):
    with pytest.raises(ValueError):
        LocalModel("m", endpoint=endpoint, post=lambda *a: pytest.fail("no request"))


def test_report_item_is_synthesized_from_the_excerpts_with_its_check():
    answer = '<think>plan</think>Gather says "every run writes a receipt" [1]. It stops "at bot checks" [2].'
    post, calls = fake_post(answer)
    item = write_report("What does Gather record?", EXCERPTS, LocalModel("qwen3:8b", post=post, clock=Tick()))
    assert item.provenance.method == "synthesized"
    assert item.provenance.derived_from == tuple(e.provenance.sha256 for e in EXCERPTS)
    assert "<think>" not in item.text and item.verify()
    check = item.meta["citation_check"]
    assert check["counts"]["verified"] == 1 and check["counts"]["too-short"] == 1
    assert item.meta["model"] == "qwen3:8b" and item.meta["elapsed_s"] == 2.0
    sent = calls[0]["body"]
    assert calls[0]["url"] == "http://127.0.0.1:11434/v1/chat/completions" and sent["temperature"] == 0
    assert "[1] E1\nEvery run writes" in sent["messages"][1]["content"]


def test_an_unverified_citation_stays_in_the_text_and_is_marked():
    post, _ = fake_post('Gather "invents facts out of nothing at all" [1].')
    item = write_report("q", EXCERPTS, LocalModel("m", post=post))
    assert "invents facts" in item.text
    assert item.meta["citation_check"]["counts"]["not-in-source"] == 1


def test_bad_answers_and_inputs_are_errors():
    with pytest.raises(RuntimeError):
        LocalModel("m", post=lambda *a: b'{"error": "no"}').chat("s", "u")
    with pytest.raises(ValueError):
        write_report("", EXCERPTS, LocalModel("m", post=fake_post("x")[0]))
    with pytest.raises(ValueError):
        write_report("q", [], LocalModel("m", post=fake_post("x")[0]))


def test_load_excerpts(tmp_path):
    path = tmp_path / "ex.json"
    path.write_text(json.dumps([{"title": "A", "text": "alpha beta"}, {"text": "gamma"}]), encoding="utf-8")
    items = load_excerpts(str(path))
    assert [i.text for i in items] == ["alpha beta", "gamma"] and items[0].provenance.method == "file-read"
    path.write_text(json.dumps([{"title": "no text"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_excerpts(str(path))


def test_cite_check_cli_gates_on_every_citation(tmp_path, capsys):
    from gather.cli import main
    ex = tmp_path / "ex.json"
    ex.write_text(json.dumps([{"text": "Every run writes a receipt you can re-check."}]), encoding="utf-8")
    good, bad = tmp_path / "good.txt", tmp_path / "bad.txt"
    good.write_text('It says "every run writes a receipt" [1].', encoding="utf-8")
    bad.write_text('It says "every run writes a receipt" [1]. And more [1].', encoding="utf-8")
    assert main(["cite-check", str(good), "--excerpts", str(ex)]) == 0
    assert main(["cite-check", str(bad), "--excerpts", str(ex), "--json"]) == 1
    out = capsys.readouterr().out
    assert '"unchecked": 1' in out
