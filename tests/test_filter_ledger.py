"""Filter ledgers: one reason per drop, counts that sum, and a recomputation that catches edits."""
import json

import pytest

from gather.filter_ledger import (
    Filter,
    apply_filters,
    read_input,
    scope_with_ledger,
    write_ledger,
)
from gather.item import make_item
from gather.ledger_verify import verify_files, verify_ledger


def item(i, text):
    return make_item(kind="document", id=f"d{i}", title=f"T{i}", text=text, source="docs", ref=f"r{i}",
                     method="file-read", fetched_at=1.0)


ITEMS = [item(0, "about tiling"), item(1, "about cats"), item(2, "tiling and cats"), item(3, "nothing")]


def test_scope_ledger_records_each_drop_with_one_reason_and_counts_sum():
    kept, led = scope_with_ledger(ITEMS, ["tiling"])
    assert [k.id for k in kept] == ["d0", "d2"]
    assert [(r["index"], r["id"], r["reason"]) for r in led["rows"]] == [(1, "d1", "out-of-scope"),
                                                                       (3, "d3", "out-of-scope")]
    assert led["kept"] + led["dropped"] == led["input"]["count"] == 4
    assert led["by_reason"] == {"out-of-scope": 2} and verify_ledger(led, ITEMS) == []


def test_the_first_rejecting_filter_names_the_reason():
    short = Filter("too-short", lambda it: len(it.text) > 7)
    cats = Filter("mentions-cats", lambda it: "cats" not in it.text)
    _, led = apply_filters(ITEMS + [item(4, "cats")], [short, cats])
    assert {r["id"]: r["reason"] for r in led["rows"]} == {"d1": "mentions-cats", "d2": "mentions-cats",
                                                          "d3": "too-short", "d4": "too-short"}
    assert sum(led["by_reason"].values()) == led["dropped"] == 4


def test_no_terms_drops_nothing():
    kept, led = scope_with_ledger(ITEMS, [])
    assert len(kept) == 4 and led["rows"] == [] and verify_ledger(led, ITEMS) == []


@pytest.mark.parametrize("edit,expect", [
    (lambda L: L.update(kept=L["kept"] + 1), "plus dropped"),
    (lambda L: L["by_reason"].update({"out-of-scope": 5}), "counts by reason"),
    (lambda L: L["rows"].pop(), "rows"),
    (lambda L: L["rows"][0].update(index=0), "does not match"),
    (lambda L: L["rows"][0].update(reason=""), "no reason"),
    (lambda L: L["rows"].append(dict(L["rows"][0])), "more than once"),
    (lambda L: L["input"].update(count=9), "input items"),
])
def test_an_edited_ledger_does_not_recompute(edit, expect):
    _, led = scope_with_ledger(ITEMS, ["tiling"])
    edit(led)
    problems = verify_ledger(led, ITEMS)
    assert problems and any(expect in p for p in problems), problems


def test_a_changed_input_does_not_recompute():
    _, led = scope_with_ledger(ITEMS, ["tiling"])
    other = ITEMS[:3] + [item(3, "something else")]
    assert any("digest" in p for p in verify_ledger(led, other))


def test_a_consistent_but_wrong_scope_ledger_is_caught_by_the_rerun():
    _, led = scope_with_ledger(ITEMS, ["tiling"])
    led["filters"][0]["terms"] = ["cats"]  # rows and counts still agree with each other
    assert verify_ledger(led, ITEMS) == ["a fresh run of the scope filter drops different items"]


def test_files_round_trip_and_tampered_input_text_is_refused(tmp_path):
    _, led = scope_with_ledger(ITEMS, ["tiling"])
    paths = write_ledger(str(tmp_path / "L"), led, ITEMS)
    assert verify_files(paths["ledger"], paths["input"]) == []
    assert [i.id for i in read_input(paths["input"])] == [i.id for i in ITEMS]
    lines = open(paths["input"], encoding="utf-8").read().splitlines()
    row = json.loads(lines[1])
    row["text"] = "about tiling now"
    lines[1] = json.dumps(row)
    open(paths["input"], "w", encoding="utf-8").write("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="line 2"):
        read_input(paths["input"])


def test_cli_writes_a_ledger_and_verify_recomputes_it(tmp_path, capsys):
    from gather.cli import main
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("about tiling\n", encoding="utf-8")
    (docs / "b.md").write_text("about cats\n", encoding="utf-8")
    out = tmp_path / "ledger"
    assert main(["docs", str(docs), "--scope", "tiling", "--ledger", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    led = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    assert payload["dropped"] == led["dropped"] == 1 and led["rows"][0]["reason"] == "out-of-scope"
    assert main(["ledger", "verify", str(out)]) == 0
    led["kept"] = 5
    (out / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    assert main(["ledger", "verify", str(out), "--json"]) == 1


def test_run_config_ledger_is_written_and_mcp_configs_cannot_name_one(tmp_path):
    from gather.grants import Grants
    from gather.run_config import plan_from_config, run_plan
    doc = tmp_path / "n.md"
    doc.write_text("about cats\n", encoding="utf-8")
    cfg = {"jobs": [{"source": "docs", "target": str(doc)}], "scope": ["tiling"], "ledger": str(tmp_path / "L")}
    record, _ = run_plan(plan_from_config(cfg))
    assert record.dropped == 1 and verify_files(str(tmp_path / "L" / "ledger.json"),
                                                str(tmp_path / "L" / "input.jsonl")) == []
    with pytest.raises(ValueError, match="ledger"):
        plan_from_config(cfg, grants=Grants())
