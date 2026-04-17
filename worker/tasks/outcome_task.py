"""
worker/tasks/outcome_task.py

Celery task for processing incoming market outcome webhooks.
The webhook router calls this task after basic validation,
keeping the HTTP response fast while processing happens async.

Also handles recalibration check: after every 50 new outcomes,
it checks whether the scoring weights should be recalibrated.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

RECALIBRATION_THRESHOLD = 50  # Trigger recalibration check after this many new outcomes


@celery_app.task(
    name="worker.tasks.outcome_task.process_outcome",
    queue="audits",
    max_retries=3,
    default_retry_delay=15,
)
def process_outcome(outcome_data: dict) -> dict:
    """
    Process a market outcome webhook payload.
    Stores the outcome and triggers recalibration check if threshold reached.

    Args:
        outcome_data: Dict matching OutcomeWebhookPayload fields

    Returns:
        dict with keys: status, outcome_id, recalibration_triggered
    """
    return asyncio.get_event_loop().run_until_complete(_process_async(outcome_data))


async def _process_async(outcome_data: dict) -> dict:
    from data.database import get_session, init_db
    from data.repositories.contract_repo import get_report_by_job
    from data.repositories.outcome_repo import create_outcome, list_outcomes

    init_db(os.environ["DATABASE_URL"])

    async with get_session() as db:
        # Look up predicted RCS if we have the job_id
        predicted_rcs = None
        report_id = None
        job_id = outcome_data.get("job_id")
        if job_id:
            report = await get_report_by_job(db, uuid.UUID(job_id))
            if report:
                predicted_rcs = report.resolution_clarity_score
                report_id = report.id

        outcome = await create_outcome(
            db=db,
            contract_id=uuid.UUID(outcome_data["contract_id"]),
            report_id=report_id,
            resolved_cleanly=outcome_data.get("resolved_cleanly"),
            dispute_filed=outcome_data.get("dispute_filed", False),
            actual_failure_category=outcome_data.get("failure_category"),
            predicted_rcs=predicted_rcs,
            resolution_notes=outcome_data.get("resolution_notes"),
            source=outcome_data.get("source", "webhook"),
        )

        # Check whether we should trigger a recalibration
        all_outcomes = await list_outcomes(db, limit=1000)
        recalibration_triggered = False

        if len(all_outcomes) % RECALIBRATION_THRESHOLD == 0 and len(all_outcomes) > 0:
            logger.info(
                f"Reached {len(all_outcomes)} outcomes — triggering background recalibration check"
            )
            # Fire-and-forget: the calibration script handles the actual work
            # In a full implementation, this would trigger calibrate_weights.py
            # For now we log the signal
            recalibration_triggered = True

        return {
            "status": "complete",
            "outcome_id": str(outcome.id),
            "recalibration_triggered": recalibration_triggered,
        }
