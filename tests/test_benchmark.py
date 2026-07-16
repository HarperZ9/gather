"""The benchmark reports an INTERVAL, not a single number, and emits a
serializable evidence artifact (environment + per-op stats) a reader can inspect
and reproduce. Timings are machine-specific, so the tests assert the SHAPE and the
invariants (min <= median <= max, iters honoured), never absolute milliseconds."""

import json

from gather.benchmark import measure, run_suite


def test_measure_reports_a_bounded_interval_not_one_number():
    stats = measure(lambda: sum(range(1000)), iters=9)
    assert stats["iters"] == 9
    assert stats["min_ms"] <= stats["median_ms"] <= stats["max_ms"]
    assert stats["min_ms"] >= 0.0


def test_measure_runs_the_thunk_exactly_iters_times():
    calls = []
    measure(lambda: calls.append(1), iters=4)
    assert len(calls) == 4


def test_run_suite_covers_every_core_op_with_a_reproducible_shape():
    ev = run_suite(elements=200, iters=3)
    assert ev["schema"] == "gather.benchmark/v1"
    assert ev["document"]["elements"] == 200 and ev["document"]["bytes"] > 0
    assert ev["iters"] == 3
    ops = {o["op"]: o for o in ev["ops"]}
    for name in ("parse_dom", "select", "to_markdown", "extract"):
        assert name in ops, name
        assert ops[name]["min_ms"] <= ops[name]["median_ms"] <= ops[name]["max_ms"]
    # the environment is on the record so a reader can compare like with like
    assert ev["env"]["python"] and ev["env"]["platform"]
    # and the whole artifact is JSON-serializable (an evidence file)
    assert json.loads(json.dumps(ev))["schema"] == "gather.benchmark/v1"


def test_select_hit_count_is_witnessed_not_assumed():
    ev = run_suite(elements=50, iters=2)
    sel = next(o for o in ev["ops"] if o["op"] == "select")
    assert sel["detail"]["hits"] == 50      # one '.r' per element, measured not guessed
