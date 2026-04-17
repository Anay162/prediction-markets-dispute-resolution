"""
data/scrapers/runner.py

Orchestrates all dispute scrapers and upserts results into the
disputes table, deduplicating by external_id.

Called nightly by the Celery beat schedule.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from data.models.dispute import DisputeRecord
from data.scrapers.manifold_resolutions import scrape_manifold_resolutions
from data.scrapers.polymarket_disputes import scrape_polymarket_disputes
from data.scrapers.uma_disputes import scrape_uma_disputes

logger = logging.getLogger(__name__)


async def run_all_scrapers(db: AsyncSession) -> dict[str, int]:
    """
    Run all scrapers concurrently, upsert results to DB.
    Returns dict of {platform: records_upserted}.
    """
    logger.info("Starting nightly dispute scrape run")

    poly_task = asyncio.create_task(scrape_polymarket_disputes(limit=200))
    uma_task = asyncio.create_task(scrape_uma_disputes(limit=300))
    manifold_task = asyncio.create_task(scrape_manifold_resolutions(limit=500))

    results = await asyncio.gather(poly_task, uma_task, manifold_task, return_exceptions=True)

    counts: dict[str, int] = {}
    all_records: list[dict] = []

    platform_names = ["polymarket", "uma", "manifold"]
    for name, result in zip(platform_names, results):
        if isinstance(result, Exception):
            logger.error(f"{name} scraper failed: {result}")
            counts[name] = 0
        else:
            counts[name] = len(result)
            all_records.extend(result)

    if all_records:
        upserted = await _upsert_disputes(db, all_records)
        logger.info(f"Dispute scrape complete. Total upserted: {upserted}. By platform: {counts}")

    return counts


async def _upsert_disputes(db: AsyncSession, records: list[dict[str, Any]]) -> int:
    """
    Upsert dispute records into the disputes table.
    Uses ON CONFLICT DO NOTHING to skip duplicates by external_id.
    """
    if not records:
        return 0

    rows = [
        {
            "source_platform": r["source_platform"],
            "external_id": r["external_id"],
            "question": r.get("question", "")[:10000],
            "resolution_criteria": (r.get("resolution_criteria") or "")[:10000] or None,
            "resolution_source": r.get("resolution_source"),
            "failure_category": r.get("failure_category"),
            "dispute_reason": r.get("dispute_reason"),
            "resolution": r.get("resolution"),
            "raw_data": r.get("raw_data", {}),
            "scraped_at": datetime.utcnow(),
            "dispute_date": r.get("dispute_date"),
        }
        for r in records
        if r.get("external_id") and r.get("question")
    ]

    if not rows:
        return 0

    stmt = pg_insert(DisputeRecord).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["external_id"])
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0
