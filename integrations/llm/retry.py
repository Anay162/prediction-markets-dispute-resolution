"""
integrations/llm/retry.py

Standalone retry and backoff utilities for LLM API calls.
Extracted from client.py so they can be used independently
and tested without instantiating a full LLMClient.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import TypeVar, Callable, Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")


def exponential_backoff(
    attempt: int,
    base: float = 1.0,
    cap: float = 30.0,
    jitter: bool = True,
) -> float:
    """
    Calculate backoff duration for a given attempt number (0-indexed).

    Sequence (base=1, cap=30, no jitter): 1s, 2s, 4s, 8s, 16s, 30s, 30s...
    With jitter: ±25% randomisation to spread out thundering herd.
    """
    delay = min(base * (2 ** attempt), cap)
    if jitter:
        delay *= (0.75 + random.random() * 0.5)
    return delay


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 3,
    retryable_exceptions: tuple = (Exception,),
    non_retryable_exceptions: tuple = (),
    base_delay: float = 1.0,
    cap_delay: float = 30.0,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs,
) -> T:
    """
    Generic async retry wrapper with exponential backoff.

    Args:
        fn: Async callable to retry
        max_retries: Maximum number of retry attempts (not counting first try)
        retryable_exceptions: Exception types that trigger a retry
        non_retryable_exceptions: Exception types that immediately re-raise
        base_delay: Base delay in seconds (doubles each attempt)
        cap_delay: Maximum delay cap in seconds
        on_retry: Optional callback(attempt, exception) called before each retry

    Returns:
        The return value of fn on success

    Raises:
        The last exception if all retries are exhausted
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except non_retryable_exceptions as e:
            raise
        except retryable_exceptions as e:
            last_exc = e
            if attempt >= max_retries:
                break

            delay = exponential_backoff(attempt, base=base_delay, cap=cap_delay)
            logger.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed "
                f"({type(e).__name__}: {e}). Retrying in {delay:.1f}s..."
            )
            if on_retry:
                on_retry(attempt, e)
            await asyncio.sleep(delay)

    raise last_exc or RuntimeError("retry_async: no attempts made")


class RetryConfig:
    """
    Reusable retry configuration that can be passed around and composed.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        cap_delay: float = 30.0,
        jitter: bool = True,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.cap_delay = cap_delay
        self.jitter = jitter

    def delay_for(self, attempt: int) -> float:
        return exponential_backoff(
            attempt,
            base=self.base_delay,
            cap=self.cap_delay,
            jitter=self.jitter,
        )

    def __repr__(self) -> str:
        return (
            f"RetryConfig(max_retries={self.max_retries}, "
            f"base={self.base_delay}s, cap={self.cap_delay}s)"
        )


# Default configs for common use cases
ANTHROPIC_RETRY = RetryConfig(max_retries=3, base_delay=1.0, cap_delay=30.0)
OPENAI_RETRY = RetryConfig(max_retries=3, base_delay=1.0, cap_delay=30.0)
ENRICHMENT_RETRY = RetryConfig(max_retries=2, base_delay=0.5, cap_delay=10.0)
