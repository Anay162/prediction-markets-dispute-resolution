"""
data/embeddings/encoder.py

Thin wrapper around the OpenAI embedding API.
Used to embed contracts and disputes for similarity search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from integrations.llm.client import LLMClient

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension
MAX_EMBED_CHARS = 8000  # Truncate to stay under token limit


async def embed_text(llm: LLMClient, text: str) -> list[float]:
    """Embed a single text string. Truncates if too long."""
    return await llm.embed(text[:MAX_EMBED_CHARS])


async def embed_batch(
    llm: LLMClient,
    texts: list[str],
    batch_size: int = 20,
) -> list[list[float]]:
    """
    Embed a list of texts, respecting rate limits with batching.
    Returns embeddings in the same order as inputs.
    """
    import asyncio

    results: list[list[float] | None] = [None] * len(texts)
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        tasks = [embed_text(llm, t) for t in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, res in enumerate(batch_results):
            if isinstance(res, Exception):
                logger.warning(f"Embedding failed for item {i + j}: {res}")
                results[i + j] = [0.0] * EMBEDDING_DIM
            else:
                results[i + j] = res
        # Small delay between batches to respect rate limits
        if i + batch_size < len(texts):
            await asyncio.sleep(0.5)

    return [r for r in results if r is not None]
