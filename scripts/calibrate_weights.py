"""
scripts/calibrate_weights.py

Tunes RCS scoring weights by comparing predicted scores against
real market resolution outcomes stored in market_outcomes.

Logic:
  - For each audited contract that has an outcome recorded:
    - If resolved_cleanly=True  → our score should have been HIGH (>=70)
    - If dispute_filed=True     → our score should have been LOW  (<50)
  - Grid-searches over penalty combinations to minimise misclassification
  - Writes the best-performing weights as a new ScoringWeight version in the DB

Usage:
    python -m scripts.calibrate_weights
    python -m scripts.calibrate_weights --dry-run   (print results, don't save)
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(dry_run: bool) -> None:
    from sqlalchemy import text

    from data.database import get_session, init_db

    init_db(os.environ["DATABASE_URL"])

    async with get_session() as db:
        # Fetch all outcomes that have a corresponding report with a score
        rows = await db.execute(
            text("""
            SELECT
                o.resolved_cleanly,
                o.dispute_filed,
                o.actual_failure_category,
                r.resolution_clarity_score,
                r.critical_count,
                r.high_count,
                r.medium_count,
                r.low_count
            FROM market_outcomes o
            JOIN reports r ON r.id = o.report_id
            WHERE r.resolution_clarity_score IS NOT NULL
              AND (o.resolved_cleanly IS NOT NULL OR o.dispute_filed = true)
        """)
        )
        outcomes = rows.fetchall()

    if not outcomes:
        logger.error("No labeled outcomes found. Run some markets through audit first.")
        return

    logger.info(f"Calibrating against {len(outcomes)} labeled outcomes")

    clean = [o for o in outcomes if o.resolved_cleanly]
    disputed = [o for o in outcomes if o.dispute_filed]
    logger.info(f"  Clean resolutions: {len(clean)}, Disputed: {len(disputed)}")

    # Grid search over penalty combinations
    critical_options = [20, 25, 30]
    high_options = [10, 12, 15]
    medium_options = [4, 5, 6]
    low_options = [1, 2, 3]

    best_accuracy = 0.0
    best_params = None

    for c_pen, h_pen, m_pen, l_pen in itertools.product(
        critical_options, high_options, medium_options, low_options
    ):
        correct = 0
        for o in outcomes:
            predicted_score = max(
                0,
                100
                - (
                    o.critical_count * c_pen
                    + o.high_count * h_pen
                    + o.medium_count * m_pen
                    + o.low_count * l_pen
                ),
            )
            # Critical cap
            if o.critical_count >= 2:
                predicted_score = min(predicted_score, 25)
            elif o.critical_count >= 1:
                predicted_score = min(predicted_score, 50)

            if (
                o.resolved_cleanly
                and predicted_score >= 70
                or o.dispute_filed
                and predicted_score < 50
            ):
                correct += 1

        accuracy = correct / len(outcomes)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_params = (c_pen, h_pen, m_pen, l_pen)

    c, h, m, l = best_params
    logger.info(
        f"\nBest weights found (accuracy={best_accuracy:.1%}):\n"
        f"  critical_penalty = {c}\n"
        f"  high_penalty     = {h}\n"
        f"  medium_penalty   = {m}\n"
        f"  low_penalty      = {l}\n"
    )

    if dry_run:
        logger.info("Dry run — not saving to database.")
        return

    # Save new weights to DB
    from sqlalchemy import update

    from data.database import get_session
    from data.models.dispute import ScoringWeight

    async with get_session() as db:
        # Deactivate current active weights
        await db.execute(
            update(ScoringWeight).where(ScoringWeight.is_active == True).values(is_active=False)
        )
        version = f"v{datetime.utcnow().strftime('%Y%m%d_%H%M')}"
        new_weights = ScoringWeight(
            version=version,
            is_active=True,
            critical_penalty=c,
            high_penalty=h,
            medium_penalty=m,
            low_penalty=l,
            category_multipliers={"adversarial_resolution": 1.2, "threshold_gaming": 1.1},
            calibration_notes=(
                f"Grid search calibration on {len(outcomes)} outcomes. "
                f"Clean: {len(clean)}, Disputed: {len(disputed)}"
            ),
            calibration_accuracy=best_accuracy,
        )
        db.add(new_weights)
        logger.info(f"Saved new weight version '{version}' to database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate RCS scoring weights")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving to DB")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
