"""
api/schemas/webhook.py

Pydantic schemas for inbound outcome webhooks from prediction market platforms.
Platforms call POST /v1/webhooks/outcome after a market resolves.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OutcomeWebhookPayload(BaseModel):
    """
    Payload sent by a platform when a market resolves.
    Maps to a MarketOutcome record.
    """
    # The contract ID we issued when the audit was submitted
    contract_id: uuid.UUID

    # The job ID of the audit (alternative lookup key)
    job_id: Optional[uuid.UUID] = None

    # Resolution result
    resolved_cleanly: Optional[bool] = None
    dispute_filed: bool = False

    # If disputed, which category best describes the failure
    # (platform's own classification — we map to our VulnerabilityCategory)
    failure_description: Optional[str] = None

    # Optional: platform's own resolution notes
    resolution_notes: Optional[str] = None

    # HMAC signature for verification (header: X-Webhook-Signature)
    # Verified in the router before this schema is parsed
    platform: str = "generic"

    resolved_at: Optional[datetime] = None


class WebhookAck(BaseModel):
    """Response body returned to the platform after webhook processing."""
    received: bool = True
    outcome_id: Optional[uuid.UUID] = None
    message: str = "Outcome recorded"
