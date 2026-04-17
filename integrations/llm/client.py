"""
integrations/llm/client.py

Unified LLM client. All LLM calls in the system go through this class.

Responsibilities:
- Routes to Anthropic Claude (primary) or OpenAI (fallback)
- Exponential backoff on rate limits and transient errors
- Token usage logging per call (feeds cost_tracker)
- Enforces a hard max_tokens ceiling per environment
- Returns raw string content; callers handle parsing
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import anthropic
import openai

logger = logging.getLogger(__name__)

# Hard ceiling — no single call should exceed this regardless of caller request
HARD_MAX_TOKENS = 8192

# Models
ANTHROPIC_PRIMARY = "claude-sonnet-4-20250514"
OPENAI_FALLBACK = "gpt-4o"
OPENAI_EMBEDDING = "text-embedding-3-small"


@dataclass
class LLMUsage:
    """Token usage for a single LLM call."""
    model: str
    input_tokens: int
    output_tokens: int
    duration_seconds: float
    call_type: str = "completion"   # "completion" | "embedding"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate. Update pricing as models change."""
        pricing = {
            "claude-sonnet-4-20250514": (0.000003, 0.000015),   # (input/tok, output/tok)
            "gpt-4o": (0.000005, 0.000015),
            "text-embedding-3-small": (0.00000002, 0.0),
        }
        in_price, out_price = pricing.get(self.model, (0.000005, 0.000015))
        return self.input_tokens * in_price + self.output_tokens * out_price


class LLMClient:
    """
    Async LLM client supporting Anthropic Claude (primary) and
    OpenAI GPT-4o (fallback). Handles retries, timeouts, and usage logging.
    """

    def __init__(
        self,
        anthropic_api_key: str,
        openai_api_key: str,
        primary_model: str = ANTHROPIC_PRIMARY,
        fallback_model: str = OPENAI_FALLBACK,
        embedding_model: str = OPENAI_EMBEDDING,
        max_retries: int = 3,
        usage_callback=None,   # Optional async callable(LLMUsage) for logging
    ):
        self._anthropic = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        self._openai = openai.AsyncOpenAI(api_key=openai_api_key)
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.embedding_model = embedding_model
        self.max_retries = max_retries
        self._usage_callback = usage_callback

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        use_fallback: bool = False,
    ) -> str:
        """
        Run a single system+user completion. Returns the text content.
        Retries on rate limits with exponential backoff.
        Falls back to OpenAI if Anthropic fails after all retries.
        """
        max_tokens = min(max_tokens, HARD_MAX_TOKENS)

        if not use_fallback:
            try:
                return await self._complete_anthropic(system, user, temperature, max_tokens)
            except Exception as e:
                logger.warning(
                    f"Anthropic failed after retries ({e}), falling back to OpenAI"
                )

        return await self._complete_openai(system, user, temperature, max_tokens)

    async def embed(self, text: str) -> list[float]:
        """
        Produce a text embedding using OpenAI text-embedding-3-small.
        Returns a 1536-dimensional float vector.
        """
        start = time.monotonic()
        response = await self._openai.embeddings.create(
            model=self.embedding_model,
            input=text,
            encoding_format="float",
        )
        duration = time.monotonic() - start
        usage = LLMUsage(
            model=self.embedding_model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=0,
            duration_seconds=duration,
            call_type="embedding",
        )
        await self._log_usage(usage)
        return response.data[0].embedding

    # ------------------------------------------------------------------
    # Anthropic implementation
    # ------------------------------------------------------------------

    async def _complete_anthropic(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                start = time.monotonic()
                response = await self._anthropic.messages.create(
                    model=self.primary_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                duration = time.monotonic() - start
                content = response.content[0].text
                usage = LLMUsage(
                    model=self.primary_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    duration_seconds=duration,
                )
                await self._log_usage(usage)
                return content

            except anthropic.RateLimitError as e:
                wait = _backoff(attempt)
                logger.warning(f"Anthropic rate limit (attempt {attempt+1}), waiting {wait}s")
                await asyncio.sleep(wait)
                last_exc = e

            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    wait = _backoff(attempt)
                    logger.warning(f"Anthropic server error {e.status_code} (attempt {attempt+1}), waiting {wait}s")
                    await asyncio.sleep(wait)
                    last_exc = e
                else:
                    raise   # 4xx errors are not retried

            except anthropic.APIConnectionError as e:
                wait = _backoff(attempt)
                logger.warning(f"Anthropic connection error (attempt {attempt+1}), waiting {wait}s")
                await asyncio.sleep(wait)
                last_exc = e

        raise last_exc or RuntimeError("Anthropic completion failed after all retries")

    # ------------------------------------------------------------------
    # OpenAI fallback implementation
    # ------------------------------------------------------------------

    async def _complete_openai(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                start = time.monotonic()
                response = await self._openai.chat.completions.create(
                    model=self.fallback_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                duration = time.monotonic() - start
                content = response.choices[0].message.content or ""
                usage = LLMUsage(
                    model=self.fallback_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    duration_seconds=duration,
                )
                await self._log_usage(usage)
                return content

            except openai.RateLimitError as e:
                wait = _backoff(attempt)
                logger.warning(f"OpenAI rate limit (attempt {attempt+1}), waiting {wait}s")
                await asyncio.sleep(wait)
                last_exc = e

            except openai.APIStatusError as e:
                if e.status_code >= 500:
                    wait = _backoff(attempt)
                    await asyncio.sleep(wait)
                    last_exc = e
                else:
                    raise

            except openai.APIConnectionError as e:
                wait = _backoff(attempt)
                await asyncio.sleep(wait)
                last_exc = e

        raise last_exc or RuntimeError("OpenAI completion failed after all retries")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _log_usage(self, usage: LLMUsage) -> None:
        logger.debug(
            f"LLM call: model={usage.model} "
            f"in={usage.input_tokens} out={usage.output_tokens} "
            f"dur={usage.duration_seconds:.2f}s "
            f"cost≈${usage.estimated_cost_usd:.4f}"
        )
        if self._usage_callback:
            try:
                await self._usage_callback(usage)
            except Exception as e:
                logger.warning(f"Usage callback failed: {e}")


def _backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff: 1s, 2s, 4s, capped at 30s."""
    return min(base * (2 ** attempt), cap)
