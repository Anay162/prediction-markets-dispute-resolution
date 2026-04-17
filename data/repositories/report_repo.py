"""
data/repositories/report_repo.py

Database operations specific to reports and findings.
Complements contract_repo.py — the split follows the spec's
file structure. contract_repo.py handles contracts; this
handles reports and findings as the primary resource.
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from data.models.contract import FindingRecord, Report


async def get_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    include_findings: bool = True,
) -> Report | None:
    """Fetch a report by its primary key."""
    q = select(Report).where(Report.id == report_id)
    if include_findings:
        q = q.options(selectinload(Report.findings))
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def get_report_by_job(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> Report | None:
    """Fetch a report by its job UUID (the Celery task ID)."""
    result = await db.execute(
        select(Report).where(Report.job_id == job_id).options(selectinload(Report.findings))
    )
    return result.scalar_one_or_none()


async def list_reports(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    min_score: int | None = None,
    max_score: int | None = None,
) -> list[Report]:
    """List reports, optionally filtered by score range."""
    q = select(Report).order_by(desc(Report.created_at)).limit(limit).offset(offset)
    if min_score is not None:
        q = q.where(Report.resolution_clarity_score >= min_score)
    if max_score is not None:
        q = q.where(Report.resolution_clarity_score <= max_score)
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_reports_for_contract(
    db: AsyncSession,
    contract_id: uuid.UUID,
) -> list[Report]:
    """Return all reports for a contract, newest first."""
    result = await db.execute(
        select(Report)
        .where(Report.contract_id == contract_id)
        .options(selectinload(Report.findings))
        .order_by(desc(Report.created_at))
    )
    return list(result.scalars().all())


async def get_score_distribution(db: AsyncSession) -> dict[str, int]:
    """
    Return count of reports in each score band.
    Used for dashboard analytics.
    """
    result = await db.execute(
        select(
            func.count().filter(Report.resolution_clarity_score >= 85).label("well_specified"),
            func.count()
            .filter(Report.resolution_clarity_score >= 70, Report.resolution_clarity_score < 85)
            .label("minor_issues"),
            func.count()
            .filter(Report.resolution_clarity_score >= 50, Report.resolution_clarity_score < 70)
            .label("moderate_risk"),
            func.count()
            .filter(Report.resolution_clarity_score >= 30, Report.resolution_clarity_score < 50)
            .label("high_risk"),
            func.count().filter(Report.resolution_clarity_score < 30).label("critical"),
        )
    )
    row = result.one()
    return {
        "well_specified": row.well_specified or 0,
        "minor_issues": row.minor_issues or 0,
        "moderate_risk": row.moderate_risk or 0,
        "high_risk": row.high_risk or 0,
        "critical": row.critical or 0,
    }


async def get_findings_for_report(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> list[FindingRecord]:
    """Return all findings for a report, sorted by severity."""
    result = await db.execute(
        select(FindingRecord)
        .where(FindingRecord.report_id == report_id)
        .order_by(FindingRecord.severity_rank)
    )
    return list(result.scalars().all())
