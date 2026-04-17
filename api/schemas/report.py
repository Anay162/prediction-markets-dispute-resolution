"""
Pydantic schemas for audit findings and the final report output.
These are the shapes that come OUT of the audit engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"  # Contract will almost certainly fail to resolve cleanly
    high = "high"  # Significant risk of dispute or ambiguous resolution
    medium = "medium"  # Exploitable but requires effort or specific conditions
    low = "low"  # Minor ambiguity, unlikely to cause real problems


class VulnerabilityCategory(str, Enum):
    source_failure = "source_failure"
    definitional_ambiguity = "definitional_ambiguity"
    threshold_gaming = "threshold_gaming"
    scope_creep = "scope_creep"
    timing_ambiguity = "timing_ambiguity"
    adversarial_resolution = "adversarial_resolution"


class Finding(BaseModel):
    """
    A single identified vulnerability in a contract.
    This is the atomic unit of the audit report.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    category: VulnerabilityCategory
    severity: Severity

    # Plain-English description of the failure scenario
    description: str

    # The exact clause or phrase from the original contract that is vulnerable
    affected_clause: str

    # Concrete rewrite that closes this specific vulnerability
    rewrite: str

    # Machine-readable diff: list of (operation, text) tuples
    # operation: "equal" | "insert" | "delete"
    diff: list[tuple[str, str]] = []

    # Supporting evidence from enrichment layer (e.g. "source URL returned 404")
    evidence: list[str] = []

    # Confidence score from the LLM analyzer (0.0 - 1.0)
    confidence: float = 1.0


class ReportOutput(BaseModel):
    """
    The complete structured audit report returned to the caller.
    This is the top-level object the API returns and the PDF is generated from.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    contract_id: uuid.UUID

    # The headline score
    resolution_clarity_score: int = Field(ge=0, le=100)

    # Score interpretation label
    score_label: str  # e.g. "High risk", "Moderate", "Well-specified"

    # All findings, sorted by severity descending
    findings: list[Finding]

    # Counts by severity for quick summary
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

    # The full rewritten contract (all rewrites applied together)
    rewritten_contract: str | None = None

    # How long the audit took in seconds
    audit_duration_seconds: float

    # Which model version produced this report
    model_version: str

    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}

    @classmethod
    def score_to_label(cls, score: int) -> str:
        if score >= 85:
            return "Well-specified"
        elif score >= 70:
            return "Minor issues"
        elif score >= 50:
            return "Moderate risk"
        elif score >= 30:
            return "High risk"
        else:
            return "Critical — do not publish"
