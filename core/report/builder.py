"""
core/report/builder.py

Assembles the final ReportOutput from:
  - The ParsedContract
  - The merged list of Findings (post-rewrite, post-diff)
  - The RCS ScoreBreakdown

Also assembles the full rewritten contract by applying all rewrites
to the original resolution criteria in order of severity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.schemas.report import Finding, ReportOutput, Severity
from core.scoring.rcs_calculator import ScoreBreakdown


def build_report(
    contract_id: uuid.UUID,
    findings: list[Finding],
    score: ScoreBreakdown,
    audit_duration_seconds: float,
    model_version: str,
    original_resolution_criteria: str,
) -> ReportOutput:
    """
    Assemble the final ReportOutput.
    """
    rewritten_contract = _assemble_rewritten_contract(original_resolution_criteria, findings)

    return ReportOutput(
        id=uuid.uuid4(),
        contract_id=contract_id,
        resolution_clarity_score=score.final_score,
        score_label=score.score_label,
        findings=findings,
        critical_count=score.critical_count,
        high_count=score.high_count,
        medium_count=score.medium_count,
        low_count=score.low_count,
        rewritten_contract=rewritten_contract,
        audit_duration_seconds=audit_duration_seconds,
        model_version=model_version,
        created_at=datetime.utcnow(),
    )


def _assemble_rewritten_contract(
    original: str,
    findings: list[Finding],
) -> str:
    """
    Produce a composite rewrite of the resolution criteria by applying
    each finding's rewrite sequentially, highest severity first.

    This is a best-effort composite — individual rewrites are designed
    to be self-contained, so we note each change with a comment.
    """
    if not findings:
        return original

    # Only include findings with actual rewrites that differ from affected clause
    rewrites = [f for f in findings if f.rewrite and f.rewrite.strip() != f.affected_clause.strip()]
    if not rewrites:
        return original

    severity_order = {
        Severity.critical: 0,
        Severity.high: 1,
        Severity.medium: 2,
        Severity.low: 3,
    }
    rewrites.sort(key=lambda f: severity_order[f.severity])

    # Build annotated rewritten contract
    lines = [
        "REWRITTEN RESOLUTION CRITERIA",
        "(Vulnerabilities addressed in order of severity)",
        "=" * 60,
        "",
    ]

    working_text = original
    for i, finding in enumerate(rewrites, 1):
        severity_label = finding.severity.value.upper()
        category_label = finding.category.value.replace("_", " ").title()
        lines.append(f"[{i}] {severity_label} — {category_label}")
        lines.append(f"Original: {finding.affected_clause}")
        lines.append(f"Rewritten: {finding.rewrite}")
        lines.append("")

        # Apply the rewrite to the working text if the affected clause is present
        if finding.affected_clause in working_text:
            working_text = working_text.replace(
                finding.affected_clause,
                finding.rewrite,
                1,  # Only replace first occurrence
            )

    lines.append("=" * 60)
    lines.append("FULL REWRITTEN TEXT:")
    lines.append("")
    lines.append(working_text)

    return "\n".join(lines)
