"""
worker/tasks/audit_task.py

The Celery task that wraps the async AuditPipeline.

Celery workers are synchronous by default. We run the async pipeline
by creating a new event loop per task invocation. This is the standard
pattern for running async code from Celery.

Task flow:
  1. Deserialise the ContractInput from the task kwargs
  2. Update job status to "running" in Redis
  3. Run the pipeline with a progress callback that writes to Redis
  4. Persist the report to the database
  5. Update job status to "complete" (or "failed") in Redis
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime

from celery import Task

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


class AuditTask(Task):
    """
    Custom Celery Task class with lazy-initialised pipeline.
    The pipeline (and its LLM client) is expensive to construct —
    we build it once per worker process and reuse it.
    """

    _pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            self._pipeline = _build_pipeline()
        return self._pipeline


@celery_app.task(
    bind=True,
    base=AuditTask,
    name="worker.tasks.audit_task.run_audit",
    max_retries=2,
    default_retry_delay=30,
)
def run_audit(self: AuditTask, job_id: str, contract_dict: dict) -> dict:
    """
    Main audit Celery task.

    Args:
        job_id: UUID string for the job (used for Redis status updates)
        contract_dict: Serialised ContractInput dict

    Returns:
        dict with keys: status, report_id, error
    """
    return asyncio.get_event_loop().run_until_complete(
        _run_audit_async(self, job_id, contract_dict)
    )


async def _run_audit_async(task: AuditTask, job_id: str, contract_dict: dict) -> dict:
    from api.schemas.contract import ContractInput
    from data.cache.redis_client import job_set_status, job_update_progress
    from data.database import get_session
    from data.repositories.contract_repo import create_contract, create_report

    job_uuid = uuid.UUID(job_id)

    # Mark job as running
    await job_set_status(
        job_id,
        {
            "job_id": job_id,
            "status": "running",
            "progress_pct": 0,
            "current_stage": "Starting",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    try:
        contract = ContractInput(**contract_dict)

        async def progress_callback(stage: str, pct: int) -> None:
            await job_update_progress(job_id, stage, pct)

        # Run the pipeline
        report = await task.pipeline.run(
            contract=contract,
            job_id=job_uuid,
            progress_callback=progress_callback,
        )

        # Persist to database
        async with get_session() as db:
            contract_record = await create_contract(
                db,
                {
                    "question": contract.question,
                    "resolution_criteria": contract.resolution_criteria,
                    "resolution_source": contract.resolution_source,
                    "close_date": contract.close_date,
                    "platform": contract.platform.value,
                    "metadata": contract.metadata,
                },
            )
            await create_report(
                db=db,
                job_id=job_uuid,
                contract_id=contract_record.id,
                report_data=report.model_dump(),
                findings=report.findings,
            )

        # Mark complete
        await job_set_status(
            job_id,
            {
                "job_id": job_id,
                "status": "complete",
                "progress_pct": 100,
                "current_stage": "Complete",
                "report_id": str(report.id),
                "contract_id": str(contract_record.id),
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        logger.info(f"Audit job {job_id} completed. Report: {report.id}")
        return {"status": "complete", "report_id": str(report.id), "error": None}

    except Exception as exc:
        logger.error(f"Audit job {job_id} failed: {exc}", exc_info=True)
        await job_set_status(
            job_id,
            {
                "job_id": job_id,
                "status": "failed",
                "progress_pct": 0,
                "current_stage": "Failed",
                "error": str(exc),
                "updated_at": datetime.utcnow().isoformat(),
            },
        )
        # Retry on unexpected errors, but not on validation errors
        if not isinstance(exc, (ValueError, TypeError)):
            raise task.retry(exc=exc) from exc
        return {"status": "failed", "report_id": None, "error": str(exc)}


def _build_pipeline():
    """Build the AuditPipeline. Called once per worker process."""
    from core.pipeline import AuditPipeline
    from data.database import get_session, init_db
    from integrations.llm.client import LLMClient

    init_db(os.environ["DATABASE_URL"])

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        primary_model=os.getenv("PRIMARY_MODEL", "claude-sonnet-4-20250514"),
    )

    return AuditPipeline(
        llm_client=llm,
        db_session_factory=get_session,
        opencorporates_api_key=os.getenv("OPENCORPORATES_API_KEY"),
    )
