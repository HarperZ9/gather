import json
import os

import pytest
from fake_ytdlp import FakeYtDlp, video_info

import gather.video_source as video_source_mod
from gather.channel import ChannelRun, merge_entries, parse_listing, tab_urls
from gather.channel_ledger import is_settled, latest_rows, pass_name, summarize
from gather.cli import main
from gather.pacing import BackoffPolicy, Pacer
from gather.store import Corpus
from gather.video_source import VideoSource

CHAN = "https://www.youtube.com/@chan"


def test_tab_urls_for_a_channel_with_or_without_a_tab_suffix():
    expected = [("videos", f"{CHAN}/videos"), ("shorts", f"{CHAN}/shorts"), ("streams", f"{CHAN}/streams")]
    assert tab_urls(CHAN) == expected
    assert tab_urls(CHAN + "/videos/") == expected
    assert tab_urls(CHAN + "/featured?view=0") == expected


def test_a_playlist_url_is_listed_as_is():
    url = "https://www.youtube.com/playlist?list=PL123"
    assert tab_urls(url, ("videos",)) == [("playlist", url)]


def test_unknown_tab_is_rejected():
    with pytest.raises(ValueError):
        tab_urls(CHAN, ("videos", "community"))


def test_parse_listing_walks_nesting_and_skips_tab_links():
    doc = {"entries": [
        {"_type": "url", "ie_key": "Youtube", "id": "a", "url": "https://www.youtube.com/watch?v=a", "title": "A"},
        {"_type": "url", "ie_key": "YoutubeTab", "id": "UCx", "url": "https://www.youtube.com/@c/shorts"},
        {"_type": "playlist", "entries": [{"ie_key": "Youtube", "id": "b", "url": "b"}]},
    ]}
    entries = parse_listing(json.dumps(doc), "videos")
    assert [(e["id"], e["url"], e["tab"]) for e in entries] == [
        ("a", "https://www.youtube.com/watch?v=a", "videos"),
        ("b", "https://www.youtube.com/watch?v=b", "videos"),
    ]


def test_parse_listing_rejects_bad_json():
    with pytest.raises(ValueError):
        parse_listing("{nope", "videos")


def test_merge_keeps_the_first_sighting_of_each_id():
    merged, dupes = merge_entries([[{"id": "a", "tab": "videos"}], [{"id": "a", "tab": "streams"},
                                                                     {"id": "b", "tab": "streams"}]])
    assert [(e["id"], e["tab"]) for e in merged] == [("a", "videos"), ("b", "streams")] and dupes == 1


def test_pass_names():
    assert pass_name("skip", True) == "metadata-comments"
    assert pass_name("skip", False) == "metadata"
    assert pass_name("only", True) == "captions"
    assert pass_name("with", False) == "full"


@pytest.mark.parametrize("row,pass_,settled", [
    ({"status": "ok", "caption": "skipped"}, "metadata-comments", True),
    ({"status": "ok", "caption": "auto"}, "captions", True),
    ({"status": "ok", "caption": "missing", "caption_reason": "none-offered"}, "captions", True),
    ({"status": "ok", "caption": "missing", "caption_reason": "rate-limited"}, "captions", False),
    ({"status": "failed", "code": "unavailable"}, "captions", True),
    ({"status": "failed", "code": "rate-limited"}, "metadata-comments", False),
    ({"status": "failed", "code": "timeout"}, "metadata", False),
    ({"status": "stopped", "code": "stopped"}, "captions", False),
])
def test_what_counts_as_settled_for_resume(row, pass_, settled):
    assert is_settled(row, pass_) is settled


def test_summary_counts_outcomes_and_reasons():
    rows = [
        {"tab": "videos", "status": "ok", "caption": "auto", "comments": 3, "comment_count_reported": 4},
        {"tab": "videos", "status": "ok", "caption": "manual", "comments": 0, "retries": 2},
        {"tab": "shorts", "status": "ok", "caption": "missing", "caption_reason": "none-offered"},
        {"tab": "shorts", "status": "failed", "code": "unavailable", "caption": "missing",
         "caption_reason": "unavailable"},
        {"tab": "streams", "status": "stopped", "caption": "missing", "caption_reason": "pass-stopped",
         "throttled": False},
    ]
    s = summarize(rows)
    assert s["entries"] == 5 and s["status"] == {"failed": 1, "ok": 3, "stopped": 1}
    assert s["captions"]["manual"] == 1 and s["captions"]["auto"] == 1 and s["captions"]["missing"] == 3
    assert s["captions"]["missing_by_reason"] == {"none-offered": 1, "pass-stopped": 1, "unavailable": 1}
    assert s["comments"] == {"total": 3, "videos_with_comments": 1, "reported_by_youtube": 4}
    assert s["failures_by_reason"] == {"unavailable": 1}
    assert s["retries"]["total"] == 2 and s["by_tab"]["shorts"] == {"failed": 1, "ok": 1}


def _source(fake, captions, comments=False):
    return VideoSource(runner=fake, captions=captions, with_comments=comments, which=lambda n: None,
                       backoff=BackoffPolicy(base=1, max_attempts=2, max_total_wait=10, jitter=0),
                       sleep=lambda s: None, log=lambda m: None)


def test_run_stops_after_the_throttle_budget_and_records_the_rest(tmp_path):
    ids = [f"v{i}" for i in range(5)]
    fake = FakeYtDlp({v: video_info(v) for v in ids})
    fake.throttle["captions"] = -1
    logs = []
    run = ChannelRun(_source(fake, "only"), Corpus(str(tmp_path)), str(tmp_path / "ledger.jsonl"), "captions",
                     Pacer(0, 0), concurrency=1, max_throttled=1, log=logs.append)
    rows = run.run([{"id": v, "url": f"https://www.youtube.com/watch?v={v}", "tab": "videos"} for v in ids])
    assert run.stop_reason and "v0" in run.stop_reason
    assert [r["status"] for r in rows] == ["ok", "stopped", "stopped", "stopped", "stopped"]
    assert rows[0]["caption_reason"] == "rate-limited" and rows[0]["throttled"]
    assert all(r["caption"] == "missing" and r["caption_reason"] == "pass-stopped" for r in rows[1:])
    assert len([c for c in fake.calls if "--load-info-json" in c]) == 2   # one video, two attempts, then stop
    assert len(latest_rows(str(tmp_path / "ledger.jsonl"))) == 5


def test_channel_command_lists_tabs_gathers_and_resumes(tmp_path, monkeypatch, capsys):
    fake = FakeYtDlp({v: video_info(v, comments=n) for v, n in (("a", 2), ("b", 0), ("s1", 1))},
                     tabs={"videos": ["a", "b"], "shorts": ["s1", "a"]})
    fake.fail["b"] = "WARNING: old version\nERROR: [youtube] b: Video unavailable\n"
    monkeypatch.setattr(video_source_mod, "subprocess_runner", fake)
    store = str(tmp_path / "corpus")
    argv = ["channel", CHAN, "--store", store, "--no-captions", "--comments", "--interval", "0",
            "--jitter", "0", "--js-runtime", "none", "--json"]
    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["pass"] == "metadata-comments"
    assert summary["listing"]["tabs"]["videos"]["listed"] == 2 and summary["listing"]["tabs"]["shorts"]["listed"] == 2
    assert summary["listing"]["tabs"]["streams"]["code"] == "no-such-tab" and summary["listing"]["unique_entries"] == 3
    assert summary["run"]["comments"]["total"] == 3
    assert summary["run"]["failures_by_reason"] == {"unavailable": 1}
    assert summary["run"]["captions"]["skipped"] == 3     # a no-captions pass skips even the failed entry
    assert os.path.exists(summary["files"]["summary"]) and os.path.exists(summary["files"]["ledger"])
    assert not any("--load-info-json" in c for c in fake.calls)   # the comment pass never asks for captions
    before = len(fake.calls)

    assert main(argv) == 0                                   # resume: everything is settled
    again = json.loads(capsys.readouterr().out)
    assert again["resume"] == {"settled_before_run": 3, "gathered_this_run": 0}
    assert len(fake.calls) - before == 3                     # only the three tab listings
    assert again["pass_totals"]["comments"]["total"] == 3


def test_channel_command_captions_pass_stops_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    fake = FakeYtDlp({v: video_info(v) for v in ("a", "b", "c")}, tabs={"videos": ["a", "b", "c"]})
    fake.throttle["captions"] = -1
    monkeypatch.setattr(video_source_mod, "subprocess_runner", fake)
    store = str(tmp_path / "corpus")
    code = main(["channel", CHAN, "--store", store, "--tabs", "videos", "--captions-only", "--concurrency", "1",
                 "--interval", "0", "--jitter", "0", "--retries", "2", "--backoff-base", "0.01", "--json"])
    summary = json.loads(capsys.readouterr().out)
    assert code == 1 and summary["stopped"]
    assert summary["run"]["captions"]["missing_by_reason"] == {"pass-stopped": 2, "rate-limited": 1}
    assert summary["settings"]["backoff"]["max_attempts"] == 2


def test_channel_command_rejects_bad_options(tmp_path, capsys):
    assert main(["channel", CHAN, "--store", str(tmp_path), "--tabs", "community"]) == 2
    assert main(["channel", CHAN, "--store", str(tmp_path), "--concurrency", "0"]) == 2
