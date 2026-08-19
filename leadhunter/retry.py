"""Retry / backoff / rate-limiting helpers.

`retry_with_backoff` retries only *retryable* failures (provider errors,
rate limits, network exceptions). Fatal errors (ConfigError, state errors)
bubble up immediately — we never mask a misconfiguration as a transient
glitch.
"""

from __future__ import annotations

import functools
import random
import threading
import time
from typing import Any, Callable, Optional

import requests

from .errors import LeadHunterError, RateLimitError

TRANSIENT_EXCEPTIONS: tuple = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, LeadHunterError):
        return exc.retryable
    if isinstance(exc, RateLimitError):
        return True
    return isinstance(exc, TRANSIENT_EXCEPTIONS)


class RateLimiter:
    """Min-interval token bucket; blocks until a call is allowed."""

    def __init__(self, min_interval_s: float = 1.0):
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._last: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval_s - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def retry_with_backoff(
    func: Callable,
    *,
    attempts: int = 3,
    base_delay_s: float = 2.0,
    max_delay_s: float = 60.0,
    jitter: bool = True,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> Any:
    """Call `func` with exponential backoff on retryable failures.

    Raises the last exception when attempts are exhausted.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except BaseException as exc:  # noqa: BLE001 — we re-raise non-retryable
            last_exc = exc
            if not is_retryable(exc) or attempt == attempts:
                raise
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            if jitter:
                delay *= random.uniform(0.5, 1.5)
            if on_retry:
                on_retry(attempt, exc)
            time.sleep(delay)
    raise last_exc  # pragma: no cover — loop always raises


def retryable(
    attempts: int = 3,
    base_delay_s: float = 2.0,
    max_delay_s: float = 60.0,
    jitter: bool = True,
):
    """Decorator form of retry_with_backoff."""

    def deco(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return retry_with_backoff(
                functools.partial(func, *args, **kwargs),
                attempts=attempts,
                base_delay_s=base_delay_s,
                max_delay_s=max_delay_s,
                jitter=jitter,
            )

        return wrapper

    return deco
