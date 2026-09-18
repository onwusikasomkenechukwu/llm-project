"""Error classification and exponential backoff with jitter.

Provider SDK exceptions are classified by duck typing rather than by importing
each SDK, so the retry policy works for adapters whose library is not installed
in this environment -- including a local OpenAI-compatible server added later.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from .config import BackoffCfg, ReliabilityCfg

T = TypeVar("T")

# Exception class names that are retryable regardless of any status code.
RETRYABLE_NAMES = frozenset(
    {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "APIConnectionTimeoutError",
        "InternalServerError",
        "ServiceUnavailableError",
        "ServerError",
        "OverloadedError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutError",
        "TransientProviderError",
    }
)

# Never retried: these mean the request itself is wrong and will fail identically.
FATAL_NAMES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "BadRequestError",
        "UnprocessableEntityError",
        "InvalidRequestError",
    }
)


class TransientProviderError(Exception):
    """Raised by adapters for a retryable condition with no native exception."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def extract_status(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


@dataclass(frozen=True)
class Classification:
    retryable: bool
    status: int | None
    reason: str


def classify(exc: BaseException, cfg: ReliabilityCfg) -> Classification:
    name = type(exc).__name__
    status = extract_status(exc)

    if name in FATAL_NAMES:
        return Classification(False, status, f"fatal exception type {name}")

    if status is not None:
        if status in cfg.retry_on_http:
            return Classification(True, status, f"http {status} in retry_on_http")
        if 400 <= status < 500:
            return Classification(False, status, f"http {status} is a client error")

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return Classification(cfg.retry_on_timeout, status, "timeout")

    if name in RETRYABLE_NAMES:
        return Classification(True, status, f"retryable exception type {name}")

    if status is not None and status >= 500:
        return Classification(True, status, f"http {status} is a server error")

    return Classification(False, status, f"unclassified exception type {name}")


def compute_delay(attempt: int, cfg: BackoffCfg, rng: random.Random | None = None) -> float:
    """Delay in seconds before the given retry.

    `attempt` is 0-based: 0 is the wait after the first failure. Full jitter
    (the default) draws uniformly from [0, cap], which is what keeps a few
    thousand queued calls from re-colliding in lockstep after a 429.
    """
    rng = rng or random
    ceiling = min(cfg.max_s, cfg.base_s * (cfg.multiplier**attempt))
    if cfg.jitter == "none":
        return ceiling
    if cfg.jitter == "equal":
        half = ceiling / 2.0
        return half + rng.uniform(0.0, half)
    return rng.uniform(0.0, ceiling)


@dataclass
class RetryOutcome:
    attempts_used: int
    classification: Classification | None = None


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    cfg: ReliabilityCfg,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
) -> tuple[T, RetryOutcome]:
    """Call `fn`, retrying retryable failures with backoff.

    `sleep` and `rng` are injectable so tests can assert the delay sequence
    without spending wall-clock time.
    """
    last_exc: BaseException | None = None
    classification: Classification | None = None

    for attempt in range(cfg.max_attempts):
        try:
            result = await fn()
            return result, RetryOutcome(attempts_used=attempt + 1, classification=classification)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            last_exc = exc
            classification = classify(exc, cfg)
            if not classification.retryable or attempt == cfg.max_attempts - 1:
                raise
            delay = compute_delay(attempt, cfg.backoff, rng)
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            await sleep(delay)

    assert last_exc is not None  # unreachable: loop either returns or raises
    raise last_exc
