"""
worker/celery_app.py

Celery application instance and configuration.
The audit task is defined in worker/tasks/audit_task.py.
"""
from __future__ import annotations

import os

from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "contract_auditor",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["worker.tasks.audit_task", "worker.tasks.scrape_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,            # Don't ack until task completes (safe retries)
    worker_prefetch_multiplier=1,   # One task at a time per worker process
    task_soft_time_limit=300,       # 5 min soft limit — task should clean up
    task_time_limit=360,            # 6 min hard limit — worker killed
    task_routes={
        "worker.tasks.audit_task.run_audit": {"queue": "audits"},
        "worker.tasks.scrape_task.scrape_disputes": {"queue": "scrapers"},
    },
)
