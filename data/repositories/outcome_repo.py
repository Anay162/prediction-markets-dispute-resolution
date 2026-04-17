"""
data/repositories/outcome_repo.py

Database operations for market resolution outcomes.
Outcomes feed the scoring calibration loop — they are the ground
truth that tells us whether our RCS predictions were accurate.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from data.models.dispute import MarketOutcome


async def create_outcome(
    db: AsyncSession,
    contract_id: uuid.UUID,
    report_id: uuid.UUID | None,
    resolved_cleanly: bool | None,
    dispute_filed: bool,
    actual_failure_category: str | None = None,
    predicted_rcs: int | None = None,
    resolution_notes: str | None = None,
    source: str = "webhook",
) -> MarketOutcome:
    """
    Record a market resolution outcome.
    Called when a platform webhook fires or when outcomes are manually entered.
    """
    record = MarketOutcome(
        id=uuid.uuid4(),
        contract_id=contract_id,
        report_id=report_id,
        resolved_cleanly=resolved_cleanly,
        dispute_filed=dispute_filed,
        actual_failure_category=actual_failure_category,
        predicted_rcs=predicted_rcs,
        resolution_notes=resolution_notes,
        source=source,
        recorded_at=datetime.utcnow(),
    )
    db.add(record)
    await db.flush()
    return record


async def get_outcome_by_contract(
    db: AsyncSession,
    contract_id: uuid.UUID,
) -> MarketOutcome | None:
    result = await db.execute(
        select(MarketOutcome)
        .where(MarketOutcome.contract_id == contract_id)
        .order_by(desc(MarketOutcome.recorded_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_outcomes(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    dispute_only: bool = False,
) -> list[MarketOutcome]:
    q = select(MarketOutcome).order_by(desc(MarketOutcome.recorded_at)).limit(limit).offset(offset)
    if dispute_only:
        q = q.where(MarketOutcome.dispute_filed == True)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_calibration_dataset(
    db: AsyncSession,
    min_outcomes: int = 10,
) -> list[dict]:
    """
    Return all outcomes that have a linked report with an RCS score.
    Used by calibrate_weights.py to tune scoring penalties.
    """
    from sqlalchemy import text

    result = await db.execute(
        text("""
        SELECT
            o.resolved_cleanly,
            o.dispute_filed,
            o.actual_failure_category,
            r.resolution_clarity_score,
            r.critical_count,
            r.high_count,
            r.medium_count,
            r.low_count
        FROM market_outcomes o
        JOIN reports r ON r.id = o.report_id
        WHERE r.resolution_clarity_score IS NOT NULL
          AND (o.resolved_cleanly IS NOT NULL OR o.dispute_filed = true)
        ORDER BY o.recorded_at DESC
    """)
    )
    rows = result.fetchall()
    return [
        {
            "resolved_cleanly": row.resolved_cleanly,
            "dispute_filed": row.dispute_filed,
            "actual_failure_category": row.actual_failure_category,
            "resolution_clarity_score": row.resolution_clarity_score,
            "critical_count": row.critical_count,
            "high_count": row.high_count,
            "medium_count": row.medium_count,
            "low_count": row.low_count,
        }
        for row in rows
    ]
