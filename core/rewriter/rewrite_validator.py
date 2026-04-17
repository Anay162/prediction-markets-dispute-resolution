"""
core/rewriter/rewrite_validator.py

Standalone rewrite validation logic.

The ClauseRewriter calls the LLM validator inline, but this module
exposes the validation logic as a standalone function so it can be:
  - Called independently in tests
  - Used in batch validation scripts
  - Extended with deterministic rule-based checks in addition to LLM validation

The LLM validator is defined by core/prompts/rewrite_validator.txt.
This module adds a layer of deterministic checks that run before/after
the LLM call and can catch obvious regressions without spending tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.schemas.report import Finding


@dataclass
class ValidationResult:
    approved: bool
    quality_score: int  # 1–5
    closes_vulnerability: bool
    new_issues: list[str]
    closure_explanation: str
    suggested_improvement: str | None


def deterministic_validate(
    original_clause: str,
    rewritten_clause: str,
    finding: Finding,
) -> list[str]:
    """
    Run fast deterministic checks on a rewrite without calling the LLM.
    Returns a list of issue strings. Empty list = no issues found.

    These checks catch obvious regressions that the LLM validator sometimes misses:
    - Rewrite is identical to original (no change made)
    - Rewrite is shorter than original (likely truncated)
    - Timezone keyword was present in finding but absent in rewrite
    - "Exceeds" / "reaches" not replaced with precise comparator
    """
    issues = []

    if not rewritten_clause or not rewritten_clause.strip():
        issues.append("Rewrite is empty")
        return issues

    if rewritten_clause.strip() == original_clause.strip():
        issues.append("Rewrite is identical to original — no change made")

    if len(rewritten_clause) < len(original_clause) * 0.5:
        issues.append(
            f"Rewrite is significantly shorter than original "
            f"({len(rewritten_clause)} vs {len(original_clause)} chars) — may be truncated"
        )

    # Timezone check: if original had no timezone and finding mentions timezone,
    # the rewrite should contain a UTC reference
    desc_lower = finding.description.lower()
    if "timezone" in desc_lower or "time zone" in desc_lower or "utc" in desc_lower:
        rewrite_lower = rewritten_clause.lower()
        if "utc" not in rewrite_lower and "gmt" not in rewrite_lower:
            issues.append(
                "Finding is about timezone ambiguity but rewrite contains no UTC/GMT reference"
            )

    # Comparator precision check
    original_lower = original_clause.lower()
    rewrite_lower = rewritten_clause.lower()
    for vague in ("exceeds", "reaches", "surpasses"):
        if vague in original_lower and vague in rewrite_lower:
            if (
                "strictly greater" not in rewrite_lower
                and "greater than or equal" not in rewrite_lower
            ):
                issues.append(
                    f"Vague comparator '{vague}' still present in rewrite — "
                    f"replace with 'strictly greater than' or 'greater than or equal to'"
                )

    # Check that significant is replaced
    if "significant" in original_lower and "significant" in rewrite_lower:
        if finding.category.value == "definitional_ambiguity":
            issues.append(
                "Vague quantifier 'significant' still present — replace with a specific threshold"
            )

    return issues


def score_rewrite_quality(
    issues: list[str],
    llm_score: int,
    closes_vulnerability: bool,
) -> int:
    """
    Combine deterministic issues and LLM score into a final quality score (1–5).
    """
    if not closes_vulnerability:
        return 1
    if issues:
        # Each deterministic issue lowers the score
        penalised = llm_score - len(issues)
        return max(1, min(5, penalised))
    return max(1, min(5, llm_score))
