"""
tests/evals/run_evals.py

LLM output quality evaluation harness.

Runs the full pipeline against the golden set (golden_set.jsonl) and
computes precision/recall of finding detection vs human-labeled ground truth.

Usage:
    python -m tests.evals.run_evals
    python -m tests.evals.run_evals --fixture adversarial
    python -m tests.evals.run_evals --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "contracts"


async def run_evals(fixture_filter: str | None, verbose: bool) -> dict:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from api.schemas.contract import ContractInput, Platform
    from core.pipeline import AuditPipeline
    from integrations.llm.client import LLMClient

    # Load golden set
    if not GOLDEN_SET_PATH.exists():
        logger.error(f"Golden set not found at {GOLDEN_SET_PATH}")
        return {}

    golden = []
    with open(GOLDEN_SET_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                golden.append(json.loads(line))

    if fixture_filter:
        golden = [g for g in golden if fixture_filter in g.get("fixture", "")]

    logger.info(f"Running evals on {len(golden)} golden examples")

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    @asynccontextmanager
    async def mock_db():
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            )
        )
        yield session

    pipeline = AuditPipeline(llm_client=llm, db_session_factory=mock_db)

    results = []
    for example in golden:
        contract_path = FIXTURES_PATH / example["fixture"]
        if not contract_path.exists():
            logger.warning(f"Fixture not found: {contract_path}")
            continue

        with open(contract_path) as f:
            fixture = json.load(f)

        try:
            from datetime import date

            contract = ContractInput(
                question=fixture["question"],
                resolution_criteria=fixture["resolution_criteria"],
                resolution_source=fixture["resolution_source"],
                close_date=date.fromisoformat(fixture["close_date"]),
                platform=Platform(fixture.get("platform", "generic")),
            )
        except Exception as e:
            logger.error(f"Failed to build contract from {contract_path}: {e}")
            continue

        import uuid

        logger.info(f"Evaluating: {fixture['question'][:60]}...")
        try:
            report = await pipeline.run(contract, uuid.uuid4())
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            continue

        # Compare findings against golden expected categories
        expected_categories = set(example.get("expected_categories", []))
        found_categories = {f.category.value for f in report.findings}

        tp = len(expected_categories & found_categories)
        fp = len(found_categories - expected_categories)
        fn = len(expected_categories - found_categories)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        score_ok = True
        if "expected_score_min" in example:
            score_ok = report.resolution_clarity_score >= example["expected_score_min"]
        elif "expected_score_max" in example:
            score_ok = report.resolution_clarity_score <= example["expected_score_max"]

        result = {
            "fixture": example["fixture"],
            "rcs": report.resolution_clarity_score,
            "expected_categories": list(expected_categories),
            "found_categories": list(found_categories),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "score_ok": score_ok,
            "findings_count": len(report.findings),
        }
        results.append(result)

        if verbose:
            logger.info(json.dumps(result, indent=2))

    if not results:
        logger.warning("No results produced")
        return {}

    avg_precision = sum(r["precision"] for r in results) / len(results)
    avg_recall = sum(r["recall"] for r in results) / len(results)
    avg_f1 = sum(r["f1"] for r in results) / len(results)
    score_accuracy = sum(1 for r in results if r["score_ok"]) / len(results)

    summary = {
        "total_examples": len(results),
        "avg_precision": round(avg_precision, 3),
        "avg_recall": round(avg_recall, 3),
        "avg_f1": round(avg_f1, 3),
        "score_accuracy": round(score_accuracy, 3),
        "results": results,
    }

    logger.info(
        f"\n{'=' * 50}\n"
        f"EVAL SUMMARY ({len(results)} examples)\n"
        f"  Precision:      {avg_precision:.1%}\n"
        f"  Recall:         {avg_recall:.1%}\n"
        f"  F1:             {avg_f1:.1%}\n"
        f"  Score accuracy: {score_accuracy:.1%}\n"
        f"{'=' * 50}"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Filter to a specific fixture file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_evals(fixture_filter=args.fixture, verbose=args.verbose))
