"""Backoff behaviour: delay sequence, jitter bounds, and what is retried at all."""

from __future__ import annotations

import asyncio
import random

import pytest

from llmbench.config import BackoffCfg, ReliabilityCfg
from llmbench.retry import (
    TransientProviderError,
    classify,
    compute_delay,
    with_retry,
)


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"http {status}")
        self.status_code = status


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


@pytest.fixture
def cfg() -> ReliabilityCfg:
    return ReliabilityCfg(
        max_attempts=5,
        backoff=BackoffCfg(base_s=1.0, multiplier=2.0, max_s=30.0, jitter="none"),
    )


# -- classification ---------------------------------------------------------


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
def test_retryable_statuses(cfg, status):
    assert classify(HttpError(status), cfg).retryable


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(cfg, status):
    assert not classify(HttpError(status), cfg).retryable


def test_fatal_exception_names_are_not_retried_even_without_a_status(cfg):
    assert not classify(AuthenticationError("bad key"), cfg).retryable


def test_retryable_exception_names_without_a_status(cfg):
    assert classify(RateLimitError("slow down"), cfg).retryable
    assert classify(TransientProviderError("overloaded"), cfg).retryable


def test_timeouts_follow_the_config_flag(cfg):
    assert classify(asyncio.TimeoutError(), cfg).retryable
    off = ReliabilityCfg(retry_on_timeout=False)
    assert not classify(asyncio.TimeoutError(), off).retryable


def test_unknown_exceptions_are_not_retried(cfg):
    assert not classify(ValueError("nonsense"), cfg).retryable


# -- delay ------------------------------------------------------------------


def test_delay_grows_exponentially_and_is_capped():
    cfg = BackoffCfg(base_s=1.0, multiplier=2.0, max_s=10.0, jitter="none")
    assert [compute_delay(i, cfg) for i in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


def test_full_jitter_stays_within_the_ceiling():
    cfg = BackoffCfg(base_s=1.0, multiplier=2.0, max_s=8.0, jitter="full")
    rng = random.Random(0)
    for attempt in range(6):
        ceiling = min(8.0, 1.0 * 2**attempt)
        for _ in range(50):
            assert 0.0 <= compute_delay(attempt, cfg, rng) <= ceiling


def test_equal_jitter_keeps_at_least_half_the_ceiling():
    cfg = BackoffCfg(base_s=4.0, multiplier=2.0, max_s=100.0, jitter="equal")
    rng = random.Random(0)
    for _ in range(50):
        d = compute_delay(0, cfg, rng)
        assert 2.0 <= d <= 4.0


def test_full_jitter_actually_varies():
    """Without spread, a few thousand queued calls re-collide after a 429."""
    cfg = BackoffCfg(base_s=10.0, multiplier=2.0, max_s=10.0, jitter="full")
    rng = random.Random(1)
    assert len({compute_delay(0, cfg, rng) for _ in range(40)}) > 30


# -- with_retry -------------------------------------------------------------


async def test_succeeds_after_transient_failures(cfg):
    calls = {"n": 0}
    slept: list[float] = []

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise HttpError(429)
        return "ok"

    async def fake_sleep(d):
        slept.append(d)

    result, outcome = await with_retry(flaky, cfg, sleep=fake_sleep)
    assert result == "ok"
    assert outcome.attempts_used == 3
    assert slept == [1.0, 2.0]


async def test_fatal_error_is_not_retried(cfg):
    calls = {"n": 0}
    slept: list[float] = []

    async def fatal():
        calls["n"] += 1
        raise HttpError(400)

    with pytest.raises(HttpError):
        await with_retry(fatal, cfg, sleep=lambda d: slept.append(d) or asyncio.sleep(0))
    assert calls["n"] == 1
    assert slept == []


async def test_exhaustion_raises_after_max_attempts(cfg):
    calls = {"n": 0}

    async def always_429():
        calls["n"] += 1
        raise HttpError(429)

    async def fake_sleep(d):
        return None

    with pytest.raises(HttpError):
        await with_retry(always_429, cfg, sleep=fake_sleep)
    assert calls["n"] == cfg.max_attempts


async def test_cancellation_is_not_swallowed(cfg):
    async def cancelled():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await with_retry(cancelled, cfg, sleep=lambda d: asyncio.sleep(0))


async def test_on_retry_hook_sees_each_backoff(cfg):
    seen = []

    async def flaky():
        if len(seen) < 2:
            raise HttpError(503)
        return 1

    await with_retry(
        flaky,
        cfg,
        sleep=lambda d: asyncio.sleep(0),
        on_retry=lambda attempt, delay, exc: seen.append((attempt, delay)),
    )
    assert [a for a, _ in seen] == [0, 1]
