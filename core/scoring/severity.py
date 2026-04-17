"""
core/scoring/severity.py

Severity classification utilities.

Provides a single place to:
  - Normalise raw severity strings from LLM output to the Severity enum
  - Compute severity rank for sorting (critical=1, low=4)
  - Map severity to human-readable display strings and colours
"""

from __future__ import annotations

from api.schemas.report import Severity

# All strings that should map to each severity level.
# LLMs sometimes use variants — we normalise them all here.
_SEVERITY_ALIASES: dict[str, Severity] = {
    # Critical
    "critical": Severity.critical,
    "crit": Severity.critical,
    "blocker": Severity.critical,
    "showstopper": Severity.critical,
    "severe": Severity.critical,
    # High
    "high": Severity.high,
    "major": Severity.high,
    "important": Severity.high,
    "significant": Severity.high,
    # Medium
    "medium": Severity.medium,
    "med": Severity.medium,
    "moderate": Severity.medium,
    "warning": Severity.medium,
    "minor": Severity.medium,
    # Low
    "low": Severity.low,
    "info": Severity.low,
    "informational": Severity.low,
    "trivial": Severity.low,
    "negligible": Severity.low,
    "note": Severity.low,
}

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.critical: 1,
    Severity.high: 2,
    Severity.medium: 3,
    Severity.low: 4,
}

_SEVERITY_DISPLAY: dict[Severity, dict] = {
    Severity.critical: {
        "label": "Critical",
        "color_hex": "#991b1b",
        "bg_hex": "#fecaca",
        "description": "Will almost certainly cause a resolution failure",
    },
    Severity.high: {
        "label": "High",
        "color_hex": "#92400e",
        "bg_hex": "#fde68a",
        "description": "Significant risk of dispute or ambiguous resolution",
    },
    Severity.medium: {
        "label": "Medium",
        "color_hex": "#1e3a5f",
        "bg_hex": "#bfdbfe",
        "description": "Exploitable under specific conditions",
    },
    Severity.low: {
        "label": "Low",
        "color_hex": "#14532d",
        "bg_hex": "#bbf7d0",
        "description": "Minor ambiguity, unlikely to cause real problems",
    },
}


def normalise_severity(raw: str, default: Severity = Severity.medium) -> Severity:
    """
    Convert a raw severity string (from LLM output) to a Severity enum value.
    Case-insensitive. Falls back to default if unrecognised.
    """
    normalised = raw.strip().lower()
    return _SEVERITY_ALIASES.get(normalised, default)


def severity_rank(severity: Severity) -> int:
    """Return numeric rank for sorting (1 = most severe)."""
    return _SEVERITY_RANK[severity]


def severity_display(severity: Severity) -> dict:
    """Return display metadata (label, colours, description) for a severity."""
    return _SEVERITY_DISPLAY[severity]


def sort_by_severity(findings: list, key=lambda f: f.severity) -> list:
    """Sort a list of findings by severity descending (critical first)."""
    return sorted(findings, key=lambda f: _SEVERITY_RANK[key(f)])
