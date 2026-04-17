"""
api/routers/webhooks.py

Inbound webhook endpoint for market resolution outcomes.
Platforms POST here after a market resolves to feed the
scoring calibration loop.

    POST /v1/webhooks/outcome    Record a market resolution outcome
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request

from api.dependencies import DBDep
from api.schemas.webhook import OutcomeWebhookPayload, WebhookAck
from data.repositories.contract_repo import get_report_by_job

logger = logging.getLogger(__name__)
router = APIRouter()

WEBHOOK_SECRET = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")


@router.post("/webhooks/outcome", response_model=WebhookAck)
async def receive_outcome(
    body: OutcomeWebhookPayload,
    request: Request,
    db: DBDep,
    x_webhook_signature: str | None = Header(default=None),
):
    """
    Record a market resolution outcome from a platform webhook.

    Platforms should sign the request body with HMAC-SHA256 using the
    shared secret and send it in the X-Webhook-Signature header.
    Unsigned webhooks are accepted in development (APP_ENV != production).
    """
    # Verify signature in production
    if os.getenv("APP_ENV") == "production":
        raw_body = await request.body()
        if not _verify_signature(raw_body, x_webhook_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Look up the report to get the predicted RCS
    predicted_rcs = None
    report_id = None

    if body.job_id:
        report = await get_report_by_job(db, body.job_id)
        if report:
            predicted_rcs = report.resolution_clarity_score
            report_id = report.id

    # Map platform's failure description to our VulnerabilityCategory if possible
    failure_category = _classify_failure(body.failure_description)

    from data.repositories.outcome_repo import create_outcome

    outcome = await create_outcome(
        db=db,
        contract_id=body.contract_id,
        report_id=report_id,
        resolved_cleanly=body.resolved_cleanly,
        dispute_filed=body.dispute_filed,
        actual_failure_category=failure_category,
        predicted_rcs=predicted_rcs,
        resolution_notes=body.resolution_notes,
        source="webhook",
    )

    logger.info(
        f"Outcome recorded for contract {body.contract_id}: "
        f"clean={body.resolved_cleanly}, dispute={body.dispute_filed}, "
        f"predicted_rcs={predicted_rcs}"
    )

    return WebhookAck(received=True, outcome_id=outcome.id)


def _verify_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _classify_failure(description: str | None) -> str | None:
    """
    Attempt to map a platform's free-text failure description to one of
    our VulnerabilityCategory values using keyword matching.
    """
    if not description:
        return None
    d = description.lower()
    if any(w in d for w in ["source", "url", "link", "unavailable", "404"]):
        return "source_failure"
    if any(w in d for w in ["ambiguous", "unclear", "definition", "undefined"]):
        return "definitional_ambiguity"
    if any(w in d for w in ["threshold", "manipulation", "gaming", "revision"]):
        return "threshold_gaming"
    if any(w in d for w in ["merger", "acquisition", "delisted", "bankrupt", "renamed"]):
        return "scope_creep"
    if any(w in d for w in ["timezone", "timing", "deadline", "when"]):
        return "timing_ambiguity"
    if any(w in d for w in ["dispute", "exploit", "argument", "bad faith"]):
        return "adversarial_resolution"
    return None
