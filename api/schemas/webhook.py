"""
api/schemas/webhook.py

Pydantic schemas for inbound outcome webhooks from prediction market platforms.
Platforms call POST /v1/webhooks/outcome after a market resolves.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class OutcomeWebhookPayload(BaseModel):
    """
    Payload sent by a platform when a market resolves.
    Maps to a MarketOutcome record.
    """

    # The contract ID we issued when the audit was submitted
    contract_id: uuid.UUID

    # The job ID of the audit (alternative lookup key)
    job_id: uuid.UUID | None = None

    # Resolution result
    resolved_cleanly: bool | None = None
    dispute_filed: bool = False

    # If disputed, which category best describes the failure
    # (platform's own classification — we map to our VulnerabilityCategory)
    failure_description: str | None = None

    # Optional: platform's own resolution notes
    resolution_notes: str | None = None

    # HMAC signature for verification (header: X-Webhook-Signature)
    # Verified in the router before this schema is parsed
    platform: str = "generic"

    resolved_at: datetime | None = None


class WebhookAck(BaseModel):
    """Response body returned to the platform after webhook processing."""

    received: bool = True
    outcome_id: uuid.UUID | None = None
    message: str = "Outcome recorded"
