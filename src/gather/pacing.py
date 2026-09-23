"""Polite pacing and bounded retry for rate-limited external tools.

Two pieces, both with injectable clock, sleep, and random edges so every path is testable
without waiting and without network:

- ``BackoffPolicy`` + ``run_with_backoff``: exponential backoff with jitter on a retryable
  failure (an HTTP 429, say), bounded twice: by a cap on attempts and by a cap on the total
  time spent waiting. Every retry is recorded as a dict and handed to ``on_retry``, so a
  retry is never silent.
- ``Pacer``: spaces call starts across worker threads (a minimum interval plus random jitter)
  and holds a shared cooldown any worker can extend after a rate-limit response, so a whole
  run slows down together instead of each worker hammering on its own schedule.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Exponential backoff with jitter. ``max_attempts`` counts the first try, so 1 disables
    retry. ``cap`` bounds any single wait; ``max_total_wait`` bounds the sum of all waits for
    one call. ``jitter`` scales each wait by a random factor in ``[1 - jitter, 1 + jitter]``."""

    base: float = 30.0
    factor: float = 2.0
    cap: float = 600.0
    max_attempts: int = 5
    max_total_wait: float = 1800.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.base < 0 or self.cap < 0 or self.max_total_wait < 0:
            raise ValueError("backoff base, cap, and max_total_wait must be >= 0")
        if self.factor < 1:
            raise ValueError("backoff factor must be >= 1")
        if self.max_attempts < 1:
            raise ValueError("backoff max_attempts must be >= 1")
        if not 0 <= self.jitter < 1:
            raise ValueError("backoff jitter must be in [0, 1)")

    def to_dict(self) -> dict:
        return {"base": self.base, "factor": self.factor, "cap": self.cap,
                "max_attempts": self.max_attempts, "max_total_wait": self.max_total_wait,
                "jitter": self.jitter}


def backoff_delays(policy: BackoffPolicy, rand: Callable[[], float] = random.random) -> list[float]:
    """The waits before retries 2..max_attempts. Each is ``base * factor**n`` clipped to ``cap``,
    then jittered and clipped again. A wait that would push the running total past
    ``max_total_wait`` ends the list there, so the budget holds exactly and the list can be
    shorter than ``max_attempts - 1``."""
    delays: list[float] = []
    total = 0.0
    for n in range(policy.max_attempts - 1):
        raw = min(policy.cap, policy.base * policy.factor ** n)
        wait = min(policy.cap, max(0.0, raw * (1 + policy.jitter * (2 * rand() - 1))))
        if total + wait > policy.max_total_wait:
            break
        delays.append(round(wait, 3))
        total += wait
    return delays


@dataclass(slots=True)
class RetryResult(Generic[T]):
    """What ``run_with_backoff`` returns. ``exhausted`` is True when the last try was still a
    retryable failure and the budget (attempts or total wait) ran out."""

    value: T
    retry_reason: str | None
    exhausted: bool
    attempts: list[dict] = field(default_factory=list)


def run_with_backoff(
    call: Callable[[], T],
    *,
    retryable: Callable[[T], str | None],
    policy: BackoffPolicy,
    step: str,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
    on_retry: Callable[[dict], None] | None = None,
    pacer: Pacer | None = None,
) -> RetryResult[T]:
    """Run ``call``; while ``retryable(result)`` names a reason and budget remains, wait and retry.

    Each retry is recorded as ``{step, attempt, reason, wait_s}`` in ``attempts`` and passed to
    ``on_retry`` before the wait. A ``pacer`` is told to hold for the same wait so concurrent
    workers cool down too. The final result is returned either way; the caller decides what a
    still-retryable final result means (``exhausted`` tells it)."""
    delays = backoff_delays(policy, rand)
    attempts: list[dict] = []
    result = call()
    reason = retryable(result)
    for n, wait in enumerate(delays, start=2):
        if reason is None:
            break
        record = {"step": step, "attempt": n, "reason": reason, "wait_s": wait}
        attempts.append(record)
        if on_retry is not None:
            on_retry(record)
        if pacer is not None:
            pacer.hold(wait)
        sleep(wait)
        result = call()
        reason = retryable(result)
    return RetryResult(value=result, retry_reason=reason, exhausted=reason is not None, attempts=attempts)


class Pacer:
    """Spaces call starts: at least ``interval`` seconds plus up to ``jitter`` random extra
    between consecutive starts, shared by every thread that calls ``wait``. ``hold`` pushes the
    next start out (a shared cooldown after a rate-limit response). Thread-safe: each ``wait``
    reserves its slot under a lock, then sleeps outside it."""

    def __init__(self, interval: float = 0.0, jitter: float = 0.0, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 rand: Callable[[], float] = random.random) -> None:
        if interval < 0 or jitter < 0:
            raise ValueError("pacer interval and jitter must be >= 0")
        self.interval = interval
        self.jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._rand = rand
        self._next: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Block until this caller's start slot; returns the seconds waited."""
        with self._lock:
            now = self._clock()
            start = now if self._next is None else max(now, self._next)
            self._next = start + self.interval + self.jitter * self._rand()
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return delay

    def hold(self, seconds: float) -> None:
        """Delay every future start until at least ``seconds`` from now."""
        with self._lock:
            until = self._clock() + max(0.0, seconds)
            self._next = until if self._next is None else max(self._next, until)
