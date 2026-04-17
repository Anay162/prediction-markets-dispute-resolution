"""
api/routers/reports.py

Report retrieval endpoints:
    GET    /v1/reports/{report_id}           Full report JSON
    GET    /v1/reports/{report_id}/pdf       PDF download
    GET    /v1/contracts/{contract_id}/reports  All reports for a contract
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.dependencies import AuthDep, DBDep
from api.schemas.report import Finding, ReportOutput, Severity, VulnerabilityCategory
from data.repositories.contract_repo import get_report, list_reports_for_contract

router = APIRouter()


@router.get("/reports/{report_id}", response_model=ReportOutput)
async def get_report_endpoint(
    report_id: uuid.UUID,
    db: DBDep,
    _: AuthDep,
):
    """Retrieve a full audit report by ID."""
    record = await get_report(db, report_id, include_findings=True)
    if not record:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return _orm_to_schema(record)


@router.get("/reports/{report_id}/pdf")
async def get_report_pdf(
    report_id: uuid.UUID,
    db: DBDep,
    _: AuthDep,
):
    """
    Generate and return a PDF version of the audit report.
    Uses WeasyPrint to render an HTML template to PDF.
    """
    record = await get_report(db, report_id, include_findings=True)
    if not record:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    report = _orm_to_schema(record)

    try:
        from core.report.pdf_renderer import render_pdf

        pdf_bytes = await render_pdf(report)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {e}",
        ) from e

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="audit-report-{report_id}.pdf"'},
    )


@router.get("/contracts/{contract_id}/reports", response_model=list[ReportOutput])
async def list_contract_reports(
    contract_id: uuid.UUID,
    db: DBDep,
    _: AuthDep,
):
    """List all audit reports for a given contract (most recent first)."""
    records = await list_reports_for_contract(db, contract_id)
    return [_orm_to_schema(r) for r in records]


def _orm_to_schema(record) -> ReportOutput:
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
