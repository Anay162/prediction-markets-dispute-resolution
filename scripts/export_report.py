"""
scripts/export_report.py

CLI tool to generate a PDF for a report that already exists in the database.

Usage:
    python -m scripts.export_report --report-id <uuid> --output report.pdf
    python -m scripts.export_report --report-id <uuid>        # outputs to ./report-<id>.pdf
    python -m scripts.export_report --job-id <uuid>           # look up by job ID instead
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(
    report_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
    output_path: Path,
) -> None:
    from api.schemas.report import Finding, ReportOutput, Severity, VulnerabilityCategory
    from core.report.pdf_renderer import render_pdf
    from data.database import get_session, init_db
    from data.repositories.contract_repo import get_report, get_report_by_job

    init_db(os.environ["DATABASE_URL"])

    async with get_session() as db:
        if report_id:
            record = await get_report(db, report_id, include_findings=True)
            if not record:
                logger.error(f"No report found with ID {report_id}")
                sys.exit(1)
        elif job_id:
            record = await get_report_by_job(db, job_id)
            if not record:
                logger.error(f"No report found for job ID {job_id}")
                sys.exit(1)
        else:
            logger.error("Must provide --report-id or --job-id")
            sys.exit(1)

        # Convert ORM record to Pydantic schema
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

    logger.info(
        f"Generating PDF for report {report.id} "
        f"(RCS: {report.resolution_clarity_score}, {len(report.findings)} findings)"
    )
    pdf_bytes = await render_pdf(report)
    output_path.write_bytes(pdf_bytes)
    logger.info(f"PDF written to: {output_path} ({len(pdf_bytes):,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export audit report to PDF")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report-id", type=uuid.UUID, help="Report UUID")
    group.add_argument("--job-id", type=uuid.UUID, help="Job UUID (looks up its report)")
    parser.add_argument(
        "--output", type=Path, default=None, help="Output path (default: ./report-<id>.pdf)"
    )
    args = parser.parse_args()

    target_id = args.report_id or args.job_id
    output = args.output or Path(f"report-{target_id}.pdf")

    asyncio.run(
        main(
            report_id=args.report_id,
            job_id=args.job_id,
            output_path=output,
        )
    )
