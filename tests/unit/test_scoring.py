"""
tests/unit/test_scoring.py

Unit tests for core/scoring/rcs_calculator.py

Covers: formula correctness, critical caps, empty input,
category multipliers, and score label mapping.
"""

from __future__ import annotations

import uuid

import pytest

from api.schemas.report import Finding, Severity, VulnerabilityCategory
from core.scoring.rcs_calculator import RCSCalculator, _score_to_label


def make_finding(
    severity: Severity, category=VulnerabilityCategory.definitional_ambiguity
) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        category=category,
        severity=severity,
        description="test",
        affected_clause="clause",
        rewrite="rewrite",
    )


# ---------------------------------------------------------------------------
# Base formula
# ---------------------------------------------------------------------------


def test_no_findings_returns_100():
    calc = RCSCalculator()
    result = calc.calculate([])
    assert result.final_score == 100
    assert result.score_label == "Well-specified"
    assert not result.was_capped


def test_single_low_finding():
    calc = RCSCalculator()
    result = calc.calculate([make_finding(Severity.low)])
    assert result.final_score == 98  # 100 - 2
    assert result.low_count == 1
    assert result.critical_count == 0


def test_single_medium_finding():
    calc = RCSCalculator()
    result = calc.calculate([make_finding(Severity.medium)])
    assert result.final_score == 95  # 100 - 5


def test_single_high_finding():
    calc = RCSCalculator()
    result = calc.calculate([make_finding(Severity.high)])
    assert result.final_score == 88  # 100 - 12


def test_single_critical_finding():
    calc = RCSCalculator()
    result = calc.calculate([make_finding(Severity.critical)])
    # Raw = 100 - 25 = 75, then capped at 50
    assert result.final_score == 50
    assert result.was_capped
    assert result.cap_reason is not None


def test_two_critical_findings_capped_at_25():
    calc = RCSCalculator()
    findings = [make_finding(Severity.critical), make_finding(Severity.critical)]
    result = calc.calculate(findings)
    assert result.final_score == 25
    assert result.was_capped


def test_three_criticals_still_capped_at_25():
    calc = RCSCalculator()
    findings = [make_finding(Severity.critical)] * 3
    result = calc.calculate(findings)
    assert result.final_score == 25


def test_score_floored_at_zero():
    calc = RCSCalculator()
    # 4 criticals would be 100 - 100 = 0 raw
    findings = [make_finding(Severity.critical)] * 4
    result = calc.calculate(findings)
    assert result.final_score >= 0


def test_mixed_severities():
    calc = RCSCalculator()
    findings = [
        make_finding(Severity.high),  # -12
        make_finding(Severity.medium),  # -5
        make_finding(Severity.low),  # -2
    ]
    result = calc.calculate(findings)
    assert result.final_score == 81  # 100 - 19
    assert not result.was_capped
    assert result.high_count == 1
    assert result.medium_count == 1
    assert result.low_count == 1


def test_category_multiplier_applied():
    """Adversarial resolution findings get 1.2x multiplier by default."""
    calc = RCSCalculator()
    finding = make_finding(Severity.high, category=VulnerabilityCategory.adversarial_resolution)
    result = calc.calculate([finding])
    # 100 - (12 * 1.2) = 100 - 14.4 = 85.6 → 85
    assert result.final_score == 85


def test_custom_penalties():
    calc = RCSCalculator(
        penalties={
            Severity.critical: 50,
            Severity.high: 20,
            Severity.medium: 8,
            Severity.low: 3,
        }
    )
    result = calc.calculate([make_finding(Severity.high)])
    assert result.final_score == 80  # 100 - 20


def test_penalty_by_severity_breakdown():
    calc = RCSCalculator()
    findings = [make_finding(Severity.high), make_finding(Severity.low)]
    result = calc.calculate(findings)
    assert result.penalty_by_severity["high"] == 12.0
    assert result.penalty_by_severity["low"] == 2.0
    assert result.penalty_by_severity["critical"] == 0.0


def test_penalty_by_category_breakdown():
    calc = RCSCalculator()
    findings = [
        make_finding(Severity.medium, VulnerabilityCategory.source_failure),
        make_finding(Severity.medium, VulnerabilityCategory.timing_ambiguity),
    ]
    result = calc.calculate(findings)
    assert result.penalty_by_category["source_failure"] == 5.0
    assert result.penalty_by_category["timing_ambiguity"] == 5.0


# ---------------------------------------------------------------------------
# Score labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (100, "Well-specified"),
        (90, "Well-specified"),
        (85, "Well-specified"),
        (84, "Minor issues"),
        (70, "Minor issues"),
        (69, "Moderate risk"),
        (50, "Moderate risk"),
        (49, "High risk"),
        (30, "High risk"),
        (29, "Critical — do not publish"),
        (0, "Critical — do not publish"),
    ],
)
def test_score_labels(score, expected_label):
    assert _score_to_label(score) == expected_label


def test_critical_cap_sets_correct_label():
    calc = RCSCalculator()
    result = calc.calculate([make_finding(Severity.critical)])
    assert result.score_label == "Moderate risk"  # score=50 → "Moderate risk"


def test_two_critical_cap_sets_correct_label():
    calc = RCSCalculator()
    findings = [make_finding(Severity.critical)] * 2
    result = calc.calculate(findings)
    assert (
        result.score_label == "Critical \u2014 do not publish"
    )  # score=25 < 30 → "Critical — do not publish"
