"""
data/embeddings/indexer.py

Batch re-index job for contract and dispute embeddings.
Called by the scrape_task after new disputes are loaded,
and by scripts/backfill_embeddings.py for manual runs.

Handles:
  - Fetching unembedded rows in batches
  - Generating embeddings via OpenAI
  - Writing back to the vector columns
  - Progress reporting
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data.embeddings.encoder import embed_batch
from data.embeddings.vector_store import upsert_contract_embedding, upsert_dispute_embedding

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
INTER_BATCH_DELAY = 0.5  # Seconds between batches to respect rate limits


@dataclass
class IndexResult:
    table: str
    total_found: int
    total_embedded: int
    total_failed: int


async def index_unembedded_disputes(
    db: AsyncSession,
    llm_client,
    limit: int = 500,
) -> IndexResult:
    """
    Find disputes without embeddings and generate + store them.
    """
    from data.models.dispute import DisputeRecord

    result = await db.execute(
        select(DisputeRecord).where(DisputeRecord.embedding == None).limit(limit)
    )
    records = result.scalars().all()
    total = len(records)

    if not records:
        logger.info("No unembedded disputes found")
        return IndexResult("disputes", 0, 0, 0)

    logger.info(f"Indexing {total} unembedded disputes")
    embedded, failed = 0, 0

    for i in range(0, total, BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        texts = [
            f"{r.question} {r.resolution_criteria or ''} {r.dispute_reason or ''}" for r in batch
        ]
        try:
            embeddings = await embed_batch(llm_client, texts, batch_size=BATCH_SIZE)
            for record, embedding in zip(batch, embeddings):
                await upsert_dispute_embedding(db, str(record.id), embedding)
                embedded += 1
            await db.flush()
        except Exception as e:
            logger.error(f"Batch {i}–{i + BATCH_SIZE} embed failed: {e}")
            failed += len(batch)

        if i + BATCH_SIZE < total:
            await asyncio.sleep(INTER_BATCH_DELAY)

    logger.info(f"Dispute indexing complete: {embedded} embedded, {failed} failed")
    return IndexResult("disputes", total, embedded, failed)


async def index_unembedded_contracts(
    db: AsyncSession,
    llm_client,
    limit: int = 200,
) -> IndexResult:
    """
    Find contracts without embeddings and generate + store them.
    New contracts are embedded immediately after audit completion,
    so this is mainly a catch-up job.
    """
    from data.models.contract import Contract

    result = await db.execute(select(Contract).where(Contract.embedding == None).limit(limit))
    records = result.scalars().all()
    total = len(records)

    if not records:
        return IndexResult("contracts", 0, 0, 0)

    logger.info(f"Indexing {total} unembedded contracts")
    embedded, failed = 0, 0

    for i in range(0, total, BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        texts = [f"{r.question} {r.resolution_criteria} {r.resolution_source}" for r in batch]
        try:
            embeddings = await embed_batch(llm_client, texts, batch_size=BATCH_SIZE)
            for record, embedding in zip(batch, embeddings):
                await upsert_contract_embedding(db, str(record.id), embedding)
                embedded += 1
            await db.flush()
        except Exception as e:
            logger.error(f"Batch {i}–{i + BATCH_SIZE} embed failed: {e}")
            failed += len(batch)

        if i + BATCH_SIZE < total:
            await asyncio.sleep(INTER_BATCH_DELAY)

    logger.info(f"Contract indexing complete: {embedded} embedded, {failed} failed")
    return IndexResult("contracts", total, embedded, failed)
