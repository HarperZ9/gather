"""Falsifiers for gather monitor — scheduled re-fetch with change custody.

Load-bearing: (1) an unchanged page is UNCHANGED and a changed page is CHANGED
carrying BOTH content SHAs; (2) the ledger is hash-chained and verify_ledger
catches a tampered SHA; (3) a 304 costs no re-hash and stays UNCHANGED; (4) a
fetch failure is ERROR, never a crash, and never silently UNCHANGED. Pure and
offline: a fake fetch function, an injected clock, no network, no wall time.
"""
from __future__ import annotations

import hashlib

import pytest

from gather.monitor import monitor_pass, verify_ledger


class _FakeReceipt:
    def __init__(self, body: bytes | None, status: int = 200, not_modified: bool = False):
        self.status = status
        self.not_modified = not_modified
        self.content_sha256 = "" if (not_modified or body is None) \
            else hashlib.sha256(body).hexdigest()


def _fetcher(pages: dict):
    """pages: url -> bytes | _FakeReceipt | Exception. Returns (receipt, body)."""
    def _f(url, *, etag=None, last_modified=None):
        v = pages[url]
        if isinstance(v, Exception):
            raise v
        if isinstance(v, _FakeReceipt):
            return v, None
        return _FakeReceipt(v), v
    return _f


def _clock():
    t = [1000.0]

    def _c():
        t[0] += 1.0
        return t[0]
    return _c


def test_new_then_unchanged_then_changed():
    clock = _clock()
    # pass 1: first sight -> NEW
    r1, s1 = monitor_pass(["http://a"], {}, _fetcher({"http://a": b"v1"}), clock=clock)
    assert r1["counts"]["NEW"] == 1
    assert r1["observations"][0]["content_sha256"] == hashlib.sha256(b"v1").hexdigest()
    # pass 2: same bytes -> UNCHANGED
    r2, s2 = monitor_pass(["http://a"], s1, _fetcher({"http://a": b"v1"}), clock=clock)
    assert r2["counts"]["UNCHANGED"] == 1
    # pass 3: new bytes -> CHANGED, carrying BOTH shas
    r3, s3 = monitor_pass(["http://a"], s2, _fetcher({"http://a": b"v2"}), clock=clock)
    assert r3["counts"]["CHANGED"] == 1 and r3["changed"] == ["http://a"]
    obs = r3["observations"][0]
    assert obs["prev_sha256"] == hashlib.sha256(b"v1").hexdigest()
    assert obs["content_sha256"] == hashlib.sha256(b"v2").hexdigest()


def test_ledger_is_hash_chained_and_tamper_evident():
    clock = _clock()
    _, s1 = monitor_pass(["http://a", "http://b"], {},
                         _fetcher({"http://a": b"1", "http://b": b"2"}), clock=clock)
    _, s2 = monitor_pass(["http://a"], s1, _fetcher({"http://a": b"1x"}), clock=clock)
    assert verify_ledger(s2) is True
    # flip a stored content SHA: the chain must break
    s2["ledger"][0]["content_sha256"] = "0" * 64
    assert verify_ledger(s2) is False


def test_cli_refuses_to_append_to_a_tampered_ledger(tmp_path):
    import json

    from gather.web_commands import cmd_monitor

    clock = _clock()
    _, state = monitor_pass(["http://a"], {}, _fetcher({"http://a": b"1"}), clock=clock)
    state["ledger"][0]["content_sha256"] = "0" * 64          # tamper
    sfile = tmp_path / "state.json"
    sfile.write_text(json.dumps(state), encoding="utf-8")
    srcs = tmp_path / "urls.txt"
    srcs.write_text("http://a\n", encoding="utf-8")

    class Args:
        sources = str(srcs)
        state = str(sfile)
        json = False

    with pytest.raises(SystemExit, match="hash chain"):
        cmd_monitor(Args())


def test_304_stays_unchanged_without_rehash():
    clock = _clock()
    _, s1 = monitor_pass(["http://a"], {}, _fetcher({"http://a": b"v1"}), clock=clock)
    r2, _ = monitor_pass(["http://a"], s1,
                         _fetcher({"http://a": _FakeReceipt(None, status=304, not_modified=True)}),
                         clock=clock)
    assert r2["counts"]["UNCHANGED"] == 1
    assert r2["observations"][0]["content_sha256"] == hashlib.sha256(b"v1").hexdigest()


def test_gone_and_error_are_distinct_and_never_crash():
    clock = _clock()
    _, s1 = monitor_pass(["http://gone", "http://err"], {},
                         _fetcher({"http://gone": b"x", "http://err": b"y"}), clock=clock)
    pages = {"http://gone": _FakeReceipt(None, status=404),
             "http://err": RuntimeError("connection reset")}
    r2, s2 = monitor_pass(["http://gone", "http://err"], s1, _fetcher(pages), clock=clock)
    assert r2["counts"]["GONE"] == 1 and r2["gone"] == ["http://gone"]
    assert r2["counts"]["ERROR"] == 1 and r2["errors"] == ["http://err"]
    # a GONE resource drops its baseline; an ERROR keeps the last-known baseline
    assert "http://gone" not in s2["baselines"]
    assert "http://err" in s2["baselines"]


def test_error_is_never_silently_unchanged():
    clock = _clock()
    _, s1 = monitor_pass(["http://a"], {}, _fetcher({"http://a": b"v1"}), clock=clock)
    r2, _ = monitor_pass(["http://a"], s1,
                         _fetcher({"http://a": RuntimeError("blocked")}), clock=clock)
    assert r2["observations"][0]["verdict"] == "ERROR"      # not rounded to UNCHANGED


def test_report_is_deterministic_given_fetch_and_clock():
    a = monitor_pass(["http://a", "http://b"], {},
                     _fetcher({"http://a": b"1", "http://b": b"2"}), clock=_clock())[0]
    b = monitor_pass(["http://a", "http://b"], {},
                     _fetcher({"http://a": b"1", "http://b": b"2"}), clock=_clock())[0]
    assert a == b
