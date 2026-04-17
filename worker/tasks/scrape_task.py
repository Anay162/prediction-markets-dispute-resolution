"""
worker/tasks/scrape_task.py

Nightly Celery task that runs all dispute scrapers and
re-embeds any disputes that don't have embeddings yet.
"""

from __future__ import annotations

import asyncio
import logging
import os

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.tasks.scrape_task.scrape_disputes", queue="scrapers")
def scrape_disputes() -> dict:
    """Run all scrapers and embed new disputes."""
    return asyncio.get_event_loop().run_until_complete(_scrape_async())


async def _scrape_async() -> dict:
    from sqlalchemy import select

    from data.database import get_session, init_db
    from data.embeddings.encoder import embed_batch
    from data.models.dispute import DisputeRecord
    from data.scrapers.runner import run_all_scrapers

    init_db(os.environ["DATABASE_URL"])

    from integrations.llm.client import LLMClient

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    async with get_session() as db:
        # Step 1: Scrape new disputes
        counts = await run_all_scrapers(db)

        # Step 2: Embed disputes that don't have embeddings yet
        result = await db.execute(
            select(DisputeRecord).where(DisputeRecord.embedding == None).limit(500)
        )
        unembedded = result.scalars().all()

        if unembedded:
            logger.info(f"Embedding {len(unembedded)} disputes without embeddings")
            texts = [
                f"{r.question} {r.resolution_criteria or ''} {r.dispute_reason or ''}"
                for r in unembedded
            ]
            embeddings = await embed_batch(llm, texts)
            for record, embedding in zip(unembedded, embeddings):
                record.embedding = embedding
            await db.flush()

        return {"scraped": counts, "embedded": len(unembedded)}
