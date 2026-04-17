"""
integrations/llm/cost_tracker.py

Accumulates LLM usage across all calls within a single audit job
and writes a summary to the database when the job completes.

Usage:
    tracker = CostTracker(job_id=job_id)
    llm_client = LLMClient(..., usage_callback=tracker.record)
    # ... run audit ...
    summary = tracker.summary()
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from integrations.llm.client import LLMUsage

logger = logging.getLogger(__name__)


@dataclass
class CostSummary:
    job_id: uuid.UUID
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_calls: int
    calls_by_model: dict[str, int]
    total_duration_seconds: float
    recorded_at: datetime = field(default_factory=datetime.utcnow)


class CostTracker:
    """
    Collects LLMUsage records for one audit job.
    Thread-safe via asyncio lock.
    """

    def __init__(self, job_id: uuid.UUID):
        self.job_id = job_id
        self._usages: list[LLMUsage] = []
        self._lock = asyncio.Lock()

    async def record(self, usage: LLMUsage) -> None:
        async with self._lock:
            self._usages.append(usage)

    def summary(self) -> CostSummary:
        calls_by_model: dict[str, int] = {}
        total_input = total_output = 0
        total_cost = total_duration = 0.0

        for u in self._usages:
            calls_by_model[u.model] = calls_by_model.get(u.model, 0) + 1
            total_input += u.input_tokens
            total_output += u.output_tokens
            total_cost += u.estimated_cost_usd
            total_duration += u.duration_seconds

        return CostSummary(
            job_id=self.job_id,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_usd=total_cost,
            total_calls=len(self._usages),
            calls_by_model=calls_by_model,
            total_duration_seconds=total_duration,
        )
