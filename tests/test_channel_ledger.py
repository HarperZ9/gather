"""A channel pass resumes from its ledger even when the last write was cut short.

``append_row`` writes a row and its newline in one call, so a final row without its newline is
a write the process never finished. Before this, every later run of the pass stopped on that
row with an uncaught ValueError, after it had already spent the tab listing calls.
"""
import json
import os

import pytest
from fake_ytdlp import FakeYtDlp, video_info

import gather.video_source as video_source_mod
from gather.channel_ledger import append_row, drop_torn_tail, latest_rows
from gather.cli import main

CHAN = "https://www.youtube.com/@chan"


def _rows():
    return [{"id": vid, "status": "ok", "pass": "metadata"} for vid in ("a", "b")]


def _write_rows(path, rows):
    for row in rows:
        append_row(path, row)
    with open(path, "rb") as fh:
        return fh.read()


def test_a_complete_ledger_is_left_alone(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    before = _write_rows(path, _rows())
    assert drop_torn_tail(path) == 0
    assert open(path, "rb").read() == before


def test_a_missing_or_empty_ledger_needs_nothing(tmp_path):
    assert drop_torn_tail(str(tmp_path / "absent.jsonl")) == 0
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert drop_torn_tail(str(empty)) == 0 and empty.read_bytes() == b""


@pytest.mark.parametrize("keep", [0, 1, 7])
def test_an_unterminated_final_row_is_dropped_and_the_rest_kept(tmp_path, keep):
    path = str(tmp_path / "ledger.jsonl")
    data = _write_rows(path, _rows())
    first_end = data.index(b"\n") + 1
    torn = data[:first_end] + data[first_end:first_end + keep]
    with open(path, "wb") as fh:
        fh.write(torn)
    assert drop_torn_tail(path) == keep
    assert open(path, "rb").read() == data[:first_end]
    assert list(latest_rows(path)) == ["a"]


def test_a_ledger_holding_only_a_torn_row_is_emptied(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(b'{"id": "a", "sta')
    assert drop_torn_tail(str(path)) == len(b'{"id": "a", "sta') and path.read_bytes() == b""


def test_a_malformed_row_that_ends_its_line_is_not_guessed_away(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(b'{"id": "a"}\nnot json\n{"id": "b"}\n')
    assert drop_torn_tail(str(path)) == 0
    with pytest.raises(ValueError, match="line 2"):
        latest_rows(str(path))


def _argv(store):
    # the metadata-comments pass settles entries from its ledger alone, never from the corpus
    return ["channel", CHAN, "--store", store, "--tabs", "videos", "--no-captions", "--comments",
            "--interval", "0", "--jitter", "0", "--js-runtime", "none", "--json"]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeYtDlp({v: video_info(v) for v in ("a", "b")}, tabs={"videos": ["a", "b"]})
    monkeypatch.setattr(video_source_mod, "subprocess_runner", fake)
    return fake


def test_a_run_resumes_after_a_write_was_cut_short(tmp_path, fake, capsys):
    store = str(tmp_path / "corpus")
    assert main(_argv(store)) == 0
    capsys.readouterr()
    ledger = os.path.join(store, "intake", "ledger-metadata-comments.jsonl")
    data = open(ledger, "rb").read()
    first_end = data.index(b"\n") + 1
    torn_id = json.loads(data[first_end:])["id"]
    with open(ledger, "wb") as fh:  # the second row lost its second half, as a kill mid-write would
        fh.write(data[:first_end + (len(data) - first_end) // 2])
    before = len(fake.calls)

    assert main(_argv(store)) == 0
    out = capsys.readouterr()
    assert "cut short by an interrupted write" in out.err
    summary = json.loads(out.out)
    assert summary["resume"] == {"settled_before_run": 1, "gathered_this_run": 1}
    extracted = [c[-1] for c in fake.calls[before:] if "--flat-playlist" not in c]
    assert extracted == [f"https://www.youtube.com/watch?v={torn_id}"]
    assert set(latest_rows(ledger)) == {"a", "b"}  # the ledger reads whole again


def test_an_unreadable_ledger_stops_the_run_before_any_call(tmp_path, fake, capsys):
    store = str(tmp_path / "corpus")
    os.makedirs(os.path.join(store, "intake"))
    with open(os.path.join(store, "intake", "ledger-metadata-comments.jsonl"), "wb") as fh:
        fh.write(b'{"id": "a", "status": "ok"}\n{broken\n')
    assert main(_argv(store)) == 1
    err = capsys.readouterr().err
    assert "channel failed: intake ledger line 2 is not valid JSON" in err
    assert fake.calls == []
