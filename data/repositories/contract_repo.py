"""
data/repositories/contract_repo.py

All database operations for contracts and reports.
Repositories are the only place that touches SQLAlchemy models directly.
The rest of the app works with Pydantic schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas.report import Finding
from data.models.contract import Contract, FindingRecord, Report

# ------------------------------------------------------------------
# Contract operations
# ------------------------------------------------------------------


async def create_contract(db: AsyncSession, contract_data: dict) -> Contract:
    """Insert a new contract row and return the ORM object."""
    record = Contract(
        id=uuid.uuid4(),
        question=contract_data["question"],
        resolution_criteria=contract_data["resolution_criteria"],
        resolution_source=contract_data["resolution_source"],
        close_date=contract_data["close_date"],
        platform=contract_data.get("platform", "generic"),
        metadata_=contract_data.get("metadata", {}),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(record)
    await db.flush()  # Get the ID without committing
    return record


async def get_contract(db: AsyncSession, contract_id: uuid.UUID) -> Contract | None:
    result = await db.execute(select(Contract).where(Contract.id == contract_id))
    return result.scalar_one_or_none()


async def list_contracts(
    db: AsyncSession,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Contract]:
    q = select(Contract).order_by(desc(Contract.created_at)).limit(limit).offset(offset)
    if platform:
        q = q.where(Contract.platform == platform)
    result = await db.execute(q)
    return list(result.scalars().all())


# ------------------------------------------------------------------
# Report operations
# ------------------------------------------------------------------


async def create_report(
    db: AsyncSession,
    job_id: uuid.UUID,
    contract_id: uuid.UUID,
    report_data: dict,
    findings: list[Finding],
) -> Report:
    """
    Insert a Report and all its FindingRecord children atomically.
    """
    severity_rank_map = {
        "critical": 1,
        "high": 2,
        "medium": 3,
        "low": 4,
    }

    report = Report(
        id=report_data.get("id", uuid.uuid4()),
        contract_id=contract_id,
        job_id=job_id,
        resolution_clarity_score=report_data["resolution_clarity_score"],
        score_label=report_data["score_label"],
        critical_count=report_data["critical_count"],
        high_count=report_data["high_count"],
        medium_count=report_data["medium_count"],
        low_count=report_data["low_count"],
        rewritten_contract=report_data.get("rewritten_contract"),
        audit_duration_seconds=report_data["audit_duration_seconds"],
        model_version=report_data["model_version"],
        created_at=datetime.utcnow(),
    )
    db.add(report)
    await db.flush()

    for finding in findings:
        fr = FindingRecord(
            id=finding.id,
            report_id=report.id,
            category=finding.category.value,
            severity=finding.severity.value,
            severity_rank=severity_rank_map.get(finding.severity.value, 4),
            description=finding.description,
            affected_clause=finding.affected_clause,
            rewrite=finding.rewrite,
            diff=finding.diff,
            evidence=finding.evidence,
            confidence=finding.confidence,
        )
        db.add(fr)

    await db.flush()
    return report


async def get_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    include_findings: bool = True,
) -> Report | None:
    q = select(Report).where(Report.id == report_id)
    if include_findings:
        q = q.options(selectinload(Report.findings))
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def get_report_by_job(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> Report | None:
    result = await db.execute(
        select(Report).where(Report.job_id == job_id).options(selectinload(Report.findings))
    )
    return result.scalar_one_or_none()


async def list_reports_for_contract(
    db: AsyncSession,
    contract_id: uuid.UUID,
) -> list[Report]:
    result = await db.execute(
        select(Report).where(Report.contract_id == contract_id).order_by(desc(Report.created_at))
    )
    return list(result.scalars().all())
