import threading

import pytest

from gather.pacing import BackoffPolicy, Pacer, backoff_delays, run_with_backoff


def mid():
    return 0.5  # jitter factor 1.0: the un-jittered wait


def test_delays_grow_exponentially_and_respect_the_single_wait_cap():
    policy = BackoffPolicy(base=10, factor=2, cap=35, max_attempts=5, max_total_wait=1000, jitter=0.2)
    assert backoff_delays(policy, mid) == [10, 20, 35, 35]


def test_jitter_scales_each_wait_within_its_band():
    policy = BackoffPolicy(base=100, factor=1, cap=1000, max_attempts=3, max_total_wait=1000, jitter=0.25)
    assert backoff_delays(policy, lambda: 0.0) == [75, 75]      # low edge: 1 - 0.25
    assert backoff_delays(policy, lambda: 1.0) == [125, 125]    # high edge: 1 + 0.25


def test_total_wait_budget_is_never_exceeded():
    policy = BackoffPolicy(base=30, factor=2, cap=600, max_attempts=10, max_total_wait=100, jitter=0.0)
    delays = backoff_delays(policy, mid)
    assert delays == [30, 60]          # the next wait (120) would push the total past 100
    assert sum(delays) <= policy.max_total_wait


def test_one_attempt_means_no_retry():
    assert backoff_delays(BackoffPolicy(max_attempts=1), mid) == []


@pytest.mark.parametrize("kwargs", [
    {"base": -1}, {"factor": 0.5}, {"max_attempts": 0}, {"jitter": 1.0}, {"max_total_wait": -5},
])
def test_policy_rejects_nonsense(kwargs):
    with pytest.raises(ValueError):
        BackoffPolicy(**kwargs)


def _scripted(results):
    it = iter(results)
    return lambda: next(it)


def test_run_with_backoff_retries_until_success_and_records_each_retry():
    slept, seen = [], []
    policy = BackoffPolicy(base=5, factor=2, cap=100, max_attempts=4, max_total_wait=100, jitter=0)
    result = run_with_backoff(
        _scripted(["429", "429", "ok"]), retryable=lambda r: "throttled" if r == "429" else None,
        policy=policy, step="captions", sleep=slept.append, rand=mid, on_retry=seen.append)
    assert result.value == "ok" and not result.exhausted and result.retry_reason is None
    assert slept == [5, 10]
    assert [a["attempt"] for a in result.attempts] == [2, 3]
    assert seen == result.attempts                     # every retry was announced, none silent
    assert all(a["step"] == "captions" and a["reason"] == "throttled" for a in result.attempts)


def test_run_with_backoff_reports_exhaustion_with_the_last_result():
    slept = []
    policy = BackoffPolicy(base=1, factor=1, cap=1, max_attempts=3, max_total_wait=10, jitter=0)
    result = run_with_backoff(lambda: "429", retryable=lambda r: "throttled", policy=policy,
                              step="metadata", sleep=slept.append, rand=mid)
    assert result.exhausted and result.value == "429" and result.retry_reason == "throttled"
    assert slept == [1, 1] and len(result.attempts) == 2


def test_non_retryable_failure_is_not_retried():
    calls = []
    result = run_with_backoff(lambda: calls.append(1) or "gone", retryable=lambda r: None,
                              policy=BackoffPolicy(), step="metadata", sleep=lambda s: None)
    assert calls == [1] and result.attempts == [] and not result.exhausted


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(round(s, 6))
        self.now += s


def test_pacer_spaces_starts_by_interval_plus_jitter():
    clock = FakeClock()
    pacer = Pacer(10, 4, clock=clock, sleep=clock.sleep, rand=lambda: 0.5)
    assert pacer.wait() == 0            # the first start is immediate
    assert pacer.wait() == 12           # 10 + 4 * 0.5
    clock.now += 30                     # a slow call: the interval already passed
    assert pacer.wait() == 0


def test_pacer_hold_delays_the_next_start():
    clock = FakeClock()
    pacer = Pacer(1, 0, clock=clock, sleep=clock.sleep)
    pacer.wait()
    pacer.hold(60)
    assert pacer.wait() == 60


def test_pacer_hands_out_distinct_slots_across_threads():
    clock = FakeClock()
    lock = threading.Lock()
    waits = []
    pacer = Pacer(5, 0, clock=clock, sleep=lambda s: None)

    def worker():
        w = pacer.wait()
        with lock:
            waits.append(w)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(waits) == [0, 5, 10, 15]   # the clock never moved, so each thread got its own slot
