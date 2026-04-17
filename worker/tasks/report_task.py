"""
worker/tasks/report_task.py

Celery task for generating PDF reports asynchronously.
PDF generation with WeasyPrint can be slow (1-3 seconds),
so for large batches we queue it rather than blocking the API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="worker.tasks.report_task.generate_pdf",
    queue="audits",
    max_retries=2,
    default_retry_delay=10,
)
def generate_pdf(report_id: str) -> dict:
    """
    Generate a PDF for an existing report and store the result.
    Currently stores as a file in /tmp — production should write to S3/GCS.

    Args:
        report_id: UUID string of the report

    Returns:
        dict with keys: status, pdf_path, error
    """
    return asyncio.get_event_loop().run_until_complete(_generate_pdf_async(report_id))


async def _generate_pdf_async(report_id: str) -> dict:

    from api.schemas.report import Finding, ReportOutput, Severity, VulnerabilityCategory
    from core.report.pdf_renderer import render_pdf
    from data.database import get_session, init_db
    from data.repositories.contract_repo import get_report

    init_db(os.environ["DATABASE_URL"])
    report_uuid = uuid.UUID(report_id)

    async with get_session() as db:
        record = await get_report(db, report_uuid, include_findings=True)
        if not record:
            return {"status": "failed", "pdf_path": None, "error": f"Report {report_id} not found"}

        findings = [
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
            for fr in (record.findings or [])
        ]
        report = ReportOutput(
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

    try:
        pdf_bytes = await render_pdf(report)
        pdf_path = f"/tmp/report-{report_id}.pdf"
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        logger.info(f"PDF generated: {pdf_path} ({len(pdf_bytes):,} bytes)")
        return {"status": "complete", "pdf_path": pdf_path, "error": None}
    except Exception as e:
        logger.error(f"PDF generation failed for {report_id}: {e}")
        return {"status": "failed", "pdf_path": None, "error": str(e)}
