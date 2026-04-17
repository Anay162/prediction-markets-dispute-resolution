"""
api/routers/audit.py

Audit endpoints:
    POST   /v1/audit                     Submit a contract for audit
    GET    /v1/audit/{job_id}/status     Poll async job status
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.audit import AuditRequest, AuditResponse, AuditStatus, AuditStatusResponse
from data.cache.redis_client import job_get_status, job_set_status
from data.database import get_db
from data.repositories.contract_repo import get_report_by_job
from worker.tasks.audit_task import run_audit

router = APIRouter()

# Contracts smaller than this char count can be run synchronously
SYNC_CHAR_LIMIT = 2000


@router.post("/audit", response_model=AuditResponse, status_code=202)
async def submit_audit(
    body: AuditRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a contract for audit.

    - If sync=True and the contract is small, runs the pipeline inline
      and returns the full report.
    - Otherwise (default), queues an async Celery job and returns a
      job_id for polling via GET /v1/audit/{job_id}/status.
    """
    job_id = uuid.uuid4()
    contract = body.contract
    total_chars = len(contract.question) + len(contract.resolution_criteria)

    use_sync = body.sync and total_chars <= SYNC_CHAR_LIMIT

    if use_sync:
        # Run synchronously — blocks until pipeline completes
        pipeline = request.app.state.pipeline
        try:
            report = await pipeline.run(
                contract=contract,
                job_id=job_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return AuditResponse(
            job_id=job_id,
            status=AuditStatus.complete,
            contract_id=report.contract_id,
            report=report,
            created_at=datetime.utcnow(),
        )

    # Initialise job status in Redis before queuing so the status
    # endpoint returns something meaningful immediately
    await job_set_status(
        str(job_id),
        {
            "job_id": str(job_id),
            "status": "pending",
            "progress_pct": 0,
            "current_stage": "Queued",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    run_audit.apply_async(
        kwargs={
            "job_id": str(job_id),
            "contract_dict": contract.model_dump(mode="json"),
        },
        task_id=str(job_id),
        queue="audits",
    )

    estimated_seconds = max(15, total_chars // 100)  # Rough estimate

    return AuditResponse(
        job_id=job_id,
        status=AuditStatus.pending,
        estimated_seconds=estimated_seconds,
        created_at=datetime.utcnow(),
    )


@router.get("/audit/{job_id}/status", response_model=AuditStatusResponse)
async def get_audit_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Poll the status of an async audit job.
    Returns the full report once status == "complete".
    """
    status_data = await job_get_status(str(job_id))
    if not status_data:
        raise HTTPException(
            status_code=404,
            detail=f"No job found with id {job_id}. Jobs expire after 24 hours.",
        )

    status = AuditStatus(status_data.get("status", "pending"))
    report = None

    # If complete, fetch the report from the database
    if status == AuditStatus.complete:
        report_record = await get_report_by_job(db, job_id)
        if report_record:
            report = _orm_report_to_schema(report_record)

    now = datetime.utcnow()
    return AuditStatusResponse(
        job_id=job_id,
        status=status,
        progress_pct=status_data.get("progress_pct", 0),
        current_stage=status_data.get("current_stage", ""),
        report=report,
        error=status_data.get("error"),
        created_at=now,
        updated_at=now,
    )


def _orm_report_to_schema(record):
    """Convert a Report ORM object to a ReportOutput Pydantic model."""
    from api.schemas.report import Finding, ReportOutput, Severity, VulnerabilityCategory

    findings = []
    for fr in record.findings or []:
        findings.append(
            Finding(
                id=fr.id,
                category=VulnerabilityCategory(fr.category),
                severity=Severity(fr.severity),
                description=fr.description,
                affected_clause=fr.affected_clause,
                rewrite=fr.rewrite,
                diff=fr.diff or [],
                evidence=fr.evidence or [],
                confidence=fr.confidence,
            )
        )

    return ReportOutput(
        id=record.id,
        contract_id=record.contract_id,
        resolution_clarity_score=record.resolution_clarity_score,
        score_label=record.score_label,
        findings=findings,
        critical_count=record.critical_count,
        high_count=record.high_count,
        medium_count=record.medium_count,
        low_count=record.low_count,
        rewritten_contract=record.rewritten_contract,
        audit_duration_seconds=record.audit_duration_seconds,
        model_version=record.model_version,
        created_at=record.created_at,
    )
