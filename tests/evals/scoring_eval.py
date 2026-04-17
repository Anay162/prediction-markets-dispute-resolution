"""
tests/evals/scoring_eval.py

Evaluates RCS scoring accuracy against real market resolution outcomes.
Measures: how often did our score correctly predict whether a contract
would resolve cleanly vs generate a dispute?

Metrics:
  - Classification accuracy (score >= 70 → predict clean, < 50 → predict dispute)
  - False negative rate (disputed markets we scored as safe)
  - False positive rate (clean markets we scored as risky)
  - Score distribution by outcome bucket

Usage:
    python -m tests.evals.scoring_eval
    python -m tests.evals.scoring_eval --min-outcomes 20
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Score thresholds for classification
SAFE_THRESHOLD = 70      # Score >= this → predict "resolves cleanly"
RISKY_THRESHOLD = 50     # Score <= this → predict "dispute risk"


async def main(min_outcomes: int) -> dict:
    from data.database import init_db, get_session
    from data.repositories.outcome_repo import get_calibration_dataset

    init_db(os.environ["DATABASE_URL"])

    async with get_session() as db:
        dataset = await get_calibration_dataset(db)

    if len(dataset) < min_outcomes:
        logger.error(
            f"Only {len(dataset)} labeled outcomes found. "
            f"Need at least {min_outcomes}. Collect more outcome data first."
        )
        return {}

    logger.info(f"Evaluating scoring accuracy on {len(dataset)} outcomes")

    # Classification buckets
    true_positives = 0   # Predicted safe, was safe
    true_negatives = 0   # Predicted risky, was disputed
    false_positives = 0  # Predicted safe, was disputed (dangerous misses)
    false_negatives = 0  # Predicted risky, was safe (over-conservative)
    ambiguous = 0        # Score in middle zone (50-70) — we don't classify these

    score_by_outcome: dict[str, list[int]] = {"clean": [], "disputed": []}

    for row in dataset:
        score = row["resolution_clarity_score"]
        is_clean = row["resolved_cleanly"]
        is_disputed = row["dispute_filed"]

        if is_clean:
            score_by_outcome["clean"].append(score)
            if score >= SAFE_THRESHOLD:
                true_positives += 1
            elif score < RISKY_THRESHOLD:
                false_negatives += 1
            else:
                ambiguous += 1
        elif is_disputed:
            score_by_outcome["disputed"].append(score)
            if score < RISKY_THRESHOLD:
                true_negatives += 1
            elif score >= SAFE_THRESHOLD:
                false_positives += 1
            else:
                ambiguous += 1

    total_classified = true_positives + true_negatives + false_positives + false_negatives
    accuracy = (true_positives + true_negatives) / total_classified if total_classified > 0 else 0

    fnr = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0
    fpr = false_negatives / (false_negatives + true_positives) if (false_negatives + true_positives) > 0 else 0

    def avg(lst): return sum(lst) / len(lst) if lst else 0

    results = {
        "total_outcomes": len(dataset),
        "total_classified": total_classified,
        "ambiguous_zone": ambiguous,
        "accuracy": round(accuracy, 3),
        "false_negative_rate": round(fnr, 3),
        "false_positive_rate": round(fpr, 3),
        "true_positives": true_positives,
        "true_negatives": true_negatives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "avg_score_clean_contracts": round(avg(score_by_outcome["clean"]), 1),
        "avg_score_disputed_contracts": round(avg(score_by_outcome["disputed"]), 1),
    }

    logger.info(
        f"\n{'='*55}\n"
        f"SCORING EVAL RESULTS ({len(dataset)} outcomes)\n"
        f"  Accuracy:             {accuracy:.1%}\n"
        f"  False negative rate:  {fnr:.1%}  (disputed but scored safe — dangerous)\n"
        f"  False positive rate:  {fpr:.1%}  (clean but scored risky — conservative)\n"
        f"  Ambiguous zone:       {ambiguous} outcomes in score range 50–70\n"
        f"  Avg score (clean):    {results['avg_score_clean_contracts']}\n"
        f"  Avg score (disputed): {results['avg_score_disputed_contracts']}\n"
        f"{'='*55}"
    )

    if fnr > 0.15:
        logger.warning(
            "False negative rate is high (>15%). Consider lowering penalty weights "
            "or running calibrate_weights.py to recalibrate."
        )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate RCS scoring accuracy")
    parser.add_argument(
        "--min-outcomes", type=int, default=10,
        help="Minimum labeled outcomes required to run eval (default: 10)"
    )
    args = parser.parse_args()
    asyncio.run(main(min_outcomes=args.min_outcomes))
