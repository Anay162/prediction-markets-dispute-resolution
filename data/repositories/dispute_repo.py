"""
data/repositories/dispute_repo.py

Database operations for the historical dispute corpus.
Provides read access to the disputes table populated by the scrapers,
and write access for the scraper runner's upsert operations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from data.models.dispute import DisputeRecord


async def get_dispute(
    db: AsyncSession,
    dispute_id: uuid.UUID,
) -> DisputeRecord | None:
    result = await db.execute(select(DisputeRecord).where(DisputeRecord.id == dispute_id))
    return result.scalar_one_or_none()


async def get_dispute_by_external_id(
    db: AsyncSession,
    external_id: str,
) -> DisputeRecord | None:
    result = await db.execute(select(DisputeRecord).where(DisputeRecord.external_id == external_id))
    return result.scalar_one_or_none()


async def list_disputes(
    db: AsyncSession,
    platform: str | None = None,
    failure_category: str | None = None,
    unlabeled_only: bool = False,
    unembedded_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[DisputeRecord]:
    """
    List disputes with optional filters.
    Used by the labeling UI and the embedding indexer.
    """
    q = select(DisputeRecord).order_by(desc(DisputeRecord.scraped_at)).limit(limit).offset(offset)
    if platform:
        q = q.where(DisputeRecord.source_platform == platform)
    if failure_category:
        q = q.where(DisputeRecord.failure_category == failure_category)
    if unlabeled_only:
        q = q.where(DisputeRecord.failure_category == None)
    if unembedded_only:
        q = q.where(DisputeRecord.embedding == None)

    result = await db.execute(q)
    return list(result.scalars().all())


async def label_dispute(
    db: AsyncSession,
    dispute_id: uuid.UUID,
    failure_category: str,
    dispute_reason: str | None = None,
) -> DisputeRecord | None:
    """
    Set the failure_category label on a dispute record.
    Called by the dispute labeling workflow.
    """
    record = await get_dispute(db, dispute_id)
    if not record:
        return None
    record.failure_category = failure_category
    if dispute_reason:
        record.dispute_reason = dispute_reason
    await db.flush()
    return record


async def get_corpus_stats(db: AsyncSession) -> dict:
    """
    Return aggregate statistics about the dispute corpus.
    Shown in the dashboard and used by report context.
    """
    result = await db.execute(
        text("""
        SELECT
            COUNT(*)                                          AS total,
            COUNT(DISTINCT source_platform)                  AS platforms,
            COUNT(CASE WHEN failure_category IS NOT NULL
                       THEN 1 END)                           AS labeled,
            COUNT(CASE WHEN embedding IS NOT NULL
                       THEN 1 END)                           AS embedded,
            MAX(scraped_at)                                  AS last_scraped
        FROM disputes
    """)
    )
    row = result.fetchone()
    if not row:
        return {"total": 0, "platforms": 0, "labeled": 0, "embedded": 0, "last_scraped": None}
    return {
        "total": row.total,
        "platforms": row.platforms,
        "labeled": row.labeled,
        "embedded": row.embedded,
        "last_scraped": row.last_scraped,
        "label_coverage_pct": round(row.labeled / row.total * 100, 1) if row.total else 0,
        "embed_coverage_pct": round(row.embedded / row.total * 100, 1) if row.total else 0,
    }


async def count_by_category(db: AsyncSession) -> dict[str, int]:
    """Return count of disputes per failure category."""
    result = await db.execute(
        select(
            DisputeRecord.failure_category,
            func.count().label("count"),
        )
        .where(DisputeRecord.failure_category != None)
        .group_by(DisputeRecord.failure_category)
        .order_by(desc("count"))
    )
    return {row.failure_category: row.count for row in result.fetchall()}
