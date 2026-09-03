"""The capability card is a claim about backends.py, not only a picture.

tests/test_repo_art.py settles whether docs/art/capability-backends.svg fits its
columns and matches the spec it was rendered from. That is a question about the
drawing. Whether the drawing is TRUE is a different question, and only the module
it describes can answer it. Every row below is driven against a registry built
with the backend that row names left out, and what comes back is held against
what the row draws. Nothing here reads the SVG.

The registry is built by hand rather than by default_registry, because that one
picks up whatever happens to be installed on the machine running the tests. The
card describes the case where nothing optional is installed, which is the case
that is the same everywhere.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gather import backends as B
from gather.dom import select
from gather.fastparse import parse_best

SPEC = (Path(__file__).resolve().parent.parent / "docs" / "art" /
        "gather.art.json")
CARD = json.loads(SPEC.read_text(encoding="utf-8"))["cards"][0]
ROWS = {field["key"]: field for field in CARD["fields"]}

URL = "https://example.invalid/app"
SHELL = "<html><body><div id='root'></div></body></html>"
REFUSED = "refused, with a reason"


def _bare() -> B.Registry:
    """What default_registry builds on a machine with no extras installed: the
    two core backends, and nothing that needs a wheel."""
    reg = B.Registry()
    reg.register(B.Backend("stdlib-fetch", frozenset({B.CAP_FETCH}),
                           lambda url: SHELL))
    reg.register(B.Backend("stdlib-parse", frozenset({"parse"})))
    return reg


def test_every_capability_the_module_names_is_a_row_on_the_card():
    """A capability added to backends.py and never drawn leaves the card saying
    the tool can be asked for four things when it can be asked for five."""
    named = {value for name, value in vars(B).items()
             if name.startswith("CAP_")}
    assert named == set(ROWS)


def test_fetch_is_served_on_a_machine_with_nothing_installed():
    """The fetch row draws stdlib-fetch under with-no-backend and says there is
    no absent case to report. default_registry registers that backend itself,
    before it looks at what is installed, so the row holds on any machine."""
    assert ROWS[B.CAP_FETCH]["value"] == "stdlib-fetch"
    served = B.default_registry(lambda url: SHELL).resolve(B.CAP_FETCH)
    assert served is not None and served.name == "stdlib-fetch"

    result = B.render(URL, registry=_bare(), require=B.CAP_FETCH)
    assert (result.status, result.backend) == ("rendered", "stdlib-fetch")


def test_fast_parse_falls_back_to_the_stdlib_parser(monkeypatch):
    """The fast-parse row draws a parser, not a refusal."""
    assert ROWS[B.CAP_FAST_PARSE]["value"] == "stdlib parser"
    monkeypatch.setattr(B, "detect_fast_parse", lambda: None)
    assert B.best_parser(_bare()) == "stdlib"


FIXTURE = ("<html><body><div class='c'><p>a</p><p>b</p></div>"
           "<a href='/x'>link</a></body></html>")


def test_the_stdlib_parser_returns_the_answer_the_native_one_does(monkeypatch):
    """The fast-parse note claims the missing backend costs time and not truth.
    Drive parse_best down both sides of its own switch and compare the trees.
    Skipped where lxml is absent, which leaves the claim untested there rather
    than assumed."""
    pytest.importorskip("lxml")
    import gather.fastparse as fastparse

    monkeypatch.setattr(fastparse, "detect_fast_parse", lambda: "lxml")
    native = parse_best(FIXTURE)
    monkeypatch.setattr(fastparse, "detect_fast_parse", lambda: None)
    stdlib = parse_best(FIXTURE)

    for selector in ("p", ".c", "a", "div"):
        assert ([(n.path, n.text_content()) for n in select(stdlib, selector)]
                == [(n.path, n.text_content()) for n in select(native, selector)]
                ), selector


def _refused(rows) -> list[str]:
    return sorted(key for key, field in rows.items()
                  if field["value"] == REFUSED)


def test_the_rows_drawn_as_refused_are_the_two_that_need_a_heavy_backend():
    assert _refused(ROWS) == sorted([B.CAP_JS, B.CAP_STEALTH])


def test_that_a_drifted_row_would_be_caught():
    """These tests read the card, so prove the reading can fail. A row whose
    value moved off the refusal no longer belongs to the refused set."""
    drifted = {**ROWS,
               B.CAP_JS: {**ROWS[B.CAP_JS], "value": "the static shell"}}
    assert _refused(drifted) != sorted([B.CAP_JS, B.CAP_STEALTH])


@pytest.mark.parametrize("capability", [B.CAP_JS, B.CAP_STEALTH])
def test_an_unmet_capability_comes_back_refused_with_a_reason(capability):
    registry = _bare()
    assert not registry.has(capability), "the driver is not in the absent case"

    result = B.render(URL, registry=registry, require=capability)
    assert result.status == "UNVERIFIABLE"
    assert result.capability == capability
    assert result.reason == f"no backend for capability {capability!r}"
    assert (result.backend, result.html, result.content_sha256) == ("", "", "")
    assert result.verify() is True


def test_the_marked_row_is_the_one_where_a_plausible_fake_exists():
    """One hot mark, and it sits on js-render. The claim behind it is that a
    static shell is right there to be handed back: the same registry serves it
    for a plain fetch. Asking for a render returns nothing instead."""
    marked = [key for key, field in ROWS.items()
              if field.get("tone", "none") != "none"]
    assert marked == [B.CAP_JS]

    registry = _bare()
    available = B.render(URL, registry=registry, require=B.CAP_FETCH)
    assert available.html == SHELL, "the shell the row warns about is right here"
    refused = B.render(URL, registry=registry, require=B.CAP_JS)
    assert (refused.html, refused.content_sha256) == ("", "")


def test_the_refusal_is_a_value_that_carries_no_page():
    """The footnote says the refusal is a result object rather than an
    exception, and that it carries no html and no hash so nothing downstream
    reads it as a page that was fetched. The record it hands on has no html
    field at all. The drawn sentence quotes the reason without the repr
    quotes, which is the only difference between the two."""
    record = B.render(URL, registry=_bare(), require=B.CAP_JS).as_dict()
    assert "html" not in record
    assert record["status"] == "UNVERIFIABLE"
    assert record["content_sha256"] == ""
    assert record["reason"] == "no backend for capability 'js-render'"
    assert record["reason"].replace("'", "") in CARD["footnote"]


def test_the_command_the_card_cites_can_be_run():
    """The card names a command a reader can run to see what their own machine
    serves. If it stops working, the card is telling people to type something
    broken."""
    prefix = 'python -c "'
    cited = CARD["source"]
    assert cited.startswith(prefix) and cited.endswith('"')

    run = subprocess.run([sys.executable, "-c", cited[len(prefix):-1]],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert ast.literal_eval(run.stdout.strip())[B.CAP_FETCH] == ["stdlib-fetch"]
