"""
scripts/seed_disputes.py

One-time (and repeatable) script to populate the disputes table
from all scrapers and generate embeddings for similarity search.

Usage:
    python -m scripts.seed_disputes
    python -m scripts.seed_disputes --platform polymarket --limit 500
    python -m scripts.seed_disputes --skip-embed
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(platform: str | None, limit: int, skip_embed: bool) -> None:
    from data.database import init_db, get_session
    from data.scrapers.runner import run_all_scrapers
    from data.scrapers.polymarket_disputes import scrape_polymarket_disputes
    from data.scrapers.uma_disputes import scrape_uma_disputes
    from data.scrapers.manifold_resolutions import scrape_manifold_resolutions
    from data.scrapers.augur_history import scrape_augur_history
    from data.scrapers.runner import _upsert_disputes
    from data.embeddings.encoder import embed_batch
    from sqlalchemy import select
    from data.models.dispute import DisputeRecord
    from integrations.llm.client import LLMClient

    init_db(os.environ["DATABASE_URL"])

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    async with get_session() as db:
        # --- Step 1: Scrape ---
        logger.info(f"Scraping disputes (platform={platform or 'all'}, limit={limit})")

        if platform == "polymarket":
            records = await scrape_polymarket_disputes(limit=limit)
        elif platform == "uma":
            records = await scrape_uma_disputes(limit=limit)
        elif platform == "manifold":
            records = await scrape_manifold_resolutions(limit=limit)
        elif platform == "augur":
            records = await scrape_augur_history(limit=limit)
        else:
            # All platforms concurrently
            results = await asyncio.gather(
                scrape_polymarket_disputes(limit=limit),
                scrape_uma_disputes(limit=limit),
                scrape_manifold_resolutions(limit=limit),
                scrape_augur_history(limit=limit),
                return_exceptions=True,
            )
            records = []
            for r in results:
                if isinstance(r, list):
                    records.extend(r)
                else:
                    logger.error(f"Scraper failed: {r}")

        logger.info(f"Total records to upsert: {len(records)}")
        upserted = await _upsert_disputes(db, records)
        logger.info(f"Upserted {upserted} new records")

        if skip_embed:
            logger.info("Skipping embedding step (--skip-embed)")
            return

        # --- Step 2: Embed ---
        result = await db.execute(
            select(DisputeRecord)
            .where(DisputeRecord.embedding == None)
            .limit(2000)
        )
        unembedded = result.scalars().all()
        logger.info(f"Embedding {len(unembedded)} records without embeddings")

        if not unembedded:
            logger.info("All records already embedded.")
            return

        texts = [
            f"{r.question} {r.resolution_criteria or ''} {r.dispute_reason or ''}"
            for r in unembedded
        ]
        embeddings = await embed_batch(llm, texts, batch_size=20)

        embedded_count = 0
        for record, embedding in zip(unembedded, embeddings):
            record.embedding = embedding
            embedded_count += 1

        await db.flush()
        logger.info(f"Successfully embedded {embedded_count} dispute records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed dispute corpus")
    parser.add_argument("--platform", choices=["polymarket", "uma", "manifold", "augur"],
                        default=None, help="Scrape only one platform (default: all)")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max records per scraper (default: 500)")
    parser.add_argument("--skip-embed", action="store_true",
                        help="Skip embedding step")
    args = parser.parse_args()

    asyncio.run(main(
        platform=args.platform,
        limit=args.limit,
        skip_embed=args.skip_embed,
    ))
