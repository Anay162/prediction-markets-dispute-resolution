"""
core/scoring/weights.py

Loads the active ScoringWeight configuration from the database
and converts it into the penalty/multiplier dicts that RCSCalculator expects.

The active weight set is determined by the is_active=True flag on the
scoring_weights table. Only one row should be active at a time.
Falls back to hardcoded defaults if DB is unavailable or no active set found.
"""

from __future__ import annotations

import logging

from api.schemas.report import Severity, VulnerabilityCategory

logger = logging.getLogger(__name__)

# Hardcoded defaults — used as fallback when DB weights are unavailable
DEFAULT_PENALTIES: dict[Severity, int] = {
    Severity.critical: 25,
    Severity.high: 12,
    Severity.medium: 5,
    Severity.low: 2,
}

DEFAULT_CATEGORY_MULTIPLIERS: dict[VulnerabilityCategory, float] = {
    VulnerabilityCategory.source_failure: 1.0,
    VulnerabilityCategory.definitional_ambiguity: 1.0,
    VulnerabilityCategory.threshold_gaming: 1.1,
    VulnerabilityCategory.scope_creep: 1.0,
    VulnerabilityCategory.timing_ambiguity: 1.0,
    VulnerabilityCategory.adversarial_resolution: 1.2,
}


async def load_active_weights(
    db,
) -> tuple[
    dict[Severity, int],
    dict[VulnerabilityCategory, float],
]:
    """
    Load the active scoring weights from the database.

    Returns:
        (penalties, category_multipliers) tuple ready for RCSCalculator

    Falls back to hardcoded defaults if:
      - No active weights row exists
      - DB query fails
    """
    try:
        from sqlalchemy import select

        from data.models.dispute import ScoringWeight

        result = await db.execute(
            select(ScoringWeight).where(ScoringWeight.is_active == True).limit(1)
        )
        record = result.scalar_one_or_none()

        if not record:
            logger.debug("No active scoring weights in DB, using defaults")
            return DEFAULT_PENALTIES, DEFAULT_CATEGORY_MULTIPLIERS

        penalties = {
            Severity.critical: record.critical_penalty,
            Severity.high: record.high_penalty,
            Severity.medium: record.medium_penalty,
            Severity.low: record.low_penalty,
        }

        # Parse category multipliers from JSONB
        raw_multipliers: dict[str, float] = record.category_multipliers or {}
        category_multipliers = dict(DEFAULT_CATEGORY_MULTIPLIERS)  # Start with defaults
        for cat_str, multiplier in raw_multipliers.items():
            try:
                cat = VulnerabilityCategory(cat_str)
                category_multipliers[cat] = float(multiplier)
            except (ValueError, TypeError):
                logger.warning(f"Unknown category in weight multipliers: {cat_str}")

        logger.debug(f"Loaded scoring weights version '{record.version}'")
        return penalties, category_multipliers

    except Exception as e:
        logger.warning(f"Failed to load scoring weights from DB ({e}), using defaults")
        return DEFAULT_PENALTIES, DEFAULT_CATEGORY_MULTIPLIERS


def get_default_weights() -> tuple[
    dict[Severity, int],
    dict[VulnerabilityCategory, float],
]:
    """Return hardcoded default weights without touching the DB."""
    return DEFAULT_PENALTIES, DEFAULT_CATEGORY_MULTIPLIERS
