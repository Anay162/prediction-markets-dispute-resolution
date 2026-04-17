"""
Resolution Clarity Score (RCS) calculator.

The RCS is a 0-100 score representing how likely a contract is to
resolve cleanly without dispute. 100 = perfectly specified, 0 = certain disaster.

Formula:
    RCS = max(0, 100 - sum(penalty_for_each_finding))

Penalties per finding:
    critical: 25 points
    high:     12 points
    medium:   5 points
    low:      2 points

Category multipliers (loaded from active ScoringWeight record in DB):
    Some categories are weighted more heavily based on historical dispute data.
    Adversarial resolution findings carry a 1.2x multiplier by default because
    they represent intentional exploits, not just ambiguity.

The score is also capped by the presence of CRITICAL findings:
    Any critical finding caps the score at 50.
    Two or more critical findings cap the score at 25.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from api.schemas.report import Finding, Severity, VulnerabilityCategory

logger = logging.getLogger(__name__)

# Default penalties — these are the values used until calibrated weights
# are loaded from the database.
DEFAULT_PENALTIES = {
    Severity.critical: 25,
    Severity.high: 12,
    Severity.medium: 5,
    Severity.low: 2,
}

# Default category multipliers — can be overridden by DB weights
DEFAULT_CATEGORY_MULTIPLIERS = {
    VulnerabilityCategory.source_failure: 1.0,
    VulnerabilityCategory.definitional_ambiguity: 1.0,
    VulnerabilityCategory.threshold_gaming: 1.1,
    VulnerabilityCategory.scope_creep: 1.0,
    VulnerabilityCategory.timing_ambiguity: 1.0,
    VulnerabilityCategory.adversarial_resolution: 1.2,
}


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of how the RCS was calculated."""

    raw_score: float  # Before floor/ceiling
    final_score: int  # After floor (0) and critical caps
    penalty_by_severity: dict[str, float]
    penalty_by_category: dict[str, float]
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    score_label: str
    was_capped: bool
    cap_reason: str | None


class RCSCalculator:
    """
    Calculates the Resolution Clarity Score for a set of findings.
    Can be initialised with custom weights (from DB) or uses defaults.
    """

    def __init__(
        self,
        penalties: dict[Severity, int] | None = None,
        category_multipliers: dict[VulnerabilityCategory, float] | None = None,
    ):
        self.penalties = penalties or DEFAULT_PENALTIES
        self.category_multipliers = category_multipliers or DEFAULT_CATEGORY_MULTIPLIERS

    def calculate(self, findings: list[Finding]) -> ScoreBreakdown:
        if not findings:
            return ScoreBreakdown(
                raw_score=100.0,
                final_score=100,
                penalty_by_severity={s.value: 0.0 for s in Severity},
                penalty_by_category={c.value: 0.0 for c in VulnerabilityCategory},
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                score_label="Well-specified",
                was_capped=False,
                cap_reason=None,
            )

        penalty_by_severity: dict[str, float] = {s.value: 0.0 for s in Severity}
        penalty_by_category: dict[str, float] = {c.value: 0.0 for c in VulnerabilityCategory}
        total_penalty = 0.0

        counts = {Severity.critical: 0, Severity.high: 0, Severity.medium: 0, Severity.low: 0}

        for finding in findings:
            base_penalty = self.penalties[finding.severity]
            multiplier = self.category_multipliers.get(finding.category, 1.0)
            weighted_penalty = base_penalty * multiplier

            penalty_by_severity[finding.severity.value] += weighted_penalty
            penalty_by_category[finding.category.value] += weighted_penalty
            total_penalty += weighted_penalty
            counts[finding.severity] += 1

        raw_score = max(0.0, 100.0 - total_penalty)
        final_score = int(raw_score)

        # Apply critical finding caps
        was_capped = False
        cap_reason = None
        if counts[Severity.critical] >= 2 and final_score > 25:
            final_score = 25
            was_capped = True
            cap_reason = f"{counts[Severity.critical]} critical findings: score capped at 25"
        elif counts[Severity.critical] >= 1 and final_score > 50:
            final_score = 50
            was_capped = True
            cap_reason = f"{counts[Severity.critical]} critical finding: score capped at 50"

        final_score = max(0, final_score)
        label = _score_to_label(final_score)

        logger.debug(
            f"RCS calculated: {final_score} "
            f"(raw: {raw_score:.1f}, total_penalty: {total_penalty:.1f}, "
            f"critical: {counts[Severity.critical]}, "
            f"capped: {was_capped})"
        )

        return ScoreBreakdown(
            raw_score=raw_score,
            final_score=final_score,
            penalty_by_severity=penalty_by_severity,
            penalty_by_category=penalty_by_category,
            critical_count=counts[Severity.critical],
            high_count=counts[Severity.high],
            medium_count=counts[Severity.medium],
            low_count=counts[Severity.low],
            score_label=label,
            was_capped=was_capped,
            cap_reason=cap_reason,
        )


def _score_to_label(score: int) -> str:
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
