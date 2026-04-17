"""
Pydantic schemas for the POST /audit request and response envelope.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from api.schemas.contract import ContractInput
from api.schemas.report import ReportOutput


class AuditStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class AuditRequest(BaseModel):
    """Body for POST /audit."""
    contract: ContractInput

    # If true, run synchronously and return the full report in one response.
    # Only allowed for small contracts; large ones are always async.
    sync: bool = False


class AuditResponse(BaseModel):
    """
    Immediate response to POST /audit.
    If sync=False (default), contains job_id for polling.
    If sync=True, contains the full report inline.
    """
    job_id: uuid.UUID
    status: AuditStatus
    contract_id: Optional[uuid.UUID] = None

    # Only populated when status == "complete"
    report: Optional[ReportOutput] = None

    # Only populated when status == "failed"
    error: Optional[str] = None

    # Estimated seconds until completion (for pending/running)
    estimated_seconds: Optional[int] = None

    created_at: datetime


class AuditStatusResponse(BaseModel):
    """Response to GET /audit/{job_id}/status."""
    job_id: uuid.UUID
    status: AuditStatus
    progress_pct: int = 0       # 0-100
    current_stage: str = ""     # e.g. "Running threshold_gaming analyzer"
    report: Optional[ReportOutput] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
