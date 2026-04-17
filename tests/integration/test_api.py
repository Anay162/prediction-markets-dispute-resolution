"""
tests/integration/test_api.py

Integration tests for the FastAPI API layer.
Uses httpx AsyncClient with mocked app.state dependencies.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def future_date(days: int = 180) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


VALID_AUDIT_BODY = {
    "contract": {
        "question": "Will US GDP growth exceed 2% in 2025?",
        "resolution_criteria": "Resolves YES if GDP exceeds 2%.",
        "resolution_source": "https://bea.gov/gdp",
        "close_date": future_date(),
        "platform": "generic",
    },
    "sync": False,
}


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /v1/audit — async path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_audit_returns_202_with_job_id(async_client):
    with (
        patch("api.routers.audit.job_set_status", new_callable=AsyncMock),
        patch("api.routers.audit.run_audit") as mock_task,
    ):
        mock_task.apply_async = MagicMock()
        response = await async_client.post("/v1/audit", json=VALID_AUDIT_BODY)

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "pending"
    uuid.UUID(body["job_id"])  # Validates it's a valid UUID


@pytest.mark.asyncio
async def test_submit_audit_invalid_close_date_past(async_client):
    body = {**VALID_AUDIT_BODY}
    body["contract"] = {**body["contract"], "close_date": "2020-01-01"}
    response = await async_client.post("/v1/audit", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_audit_empty_question_rejected(async_client):
    body = {**VALID_AUDIT_BODY}
    body["contract"] = {**body["contract"], "question": ""}
    response = await async_client.post("/v1/audit", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_audit_missing_required_field(async_client):
    body = {"contract": {"question": "Will X happen?"}}
    response = await async_client.post("/v1/audit", json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/audit/{job_id}/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_pending_job(async_client):
    job_id = str(uuid.uuid4())
    status_data = {
        "job_id": job_id,
        "status": "pending",
        "progress_pct": 0,
        "current_stage": "Queued",
        "updated_at": "2025-01-01T00:00:00",
    }
    with (
        patch("api.routers.audit.job_get_status", new_callable=AsyncMock, return_value=status_data),
        patch("api.routers.audit.get_report_by_job", new_callable=AsyncMock, return_value=None),
    ):
        response = await async_client.get(f"/v1/audit/{job_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["progress_pct"] == 0


@pytest.mark.asyncio
async def test_get_status_unknown_job_returns_404(async_client):
    with patch("api.routers.audit.job_get_status", new_callable=AsyncMock, return_value=None):
        response = await async_client.get(f"/v1/audit/{uuid.uuid4()}/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_status_invalid_uuid_format(async_client):
    response = await async_client.get("/v1/audit/not-a-uuid/status")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/contracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_contracts_returns_list(async_client):
    with patch("api.routers.contracts.list_contracts", new_callable=AsyncMock, return_value=[]):
        response = await async_client.get("/v1/contracts")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_contract_not_found(async_client):
    with patch("api.routers.contracts.get_contract", new_callable=AsyncMock, return_value=None):
        response = await async_client.get(f"/v1/contracts/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/reports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_report_not_found(async_client):
    with patch("api.routers.reports.get_report", new_callable=AsyncMock, return_value=None):
        response = await async_client.get(f"/v1/reports/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Rate limiting (unit-level check on the function)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_allows_first_request():
    from api.auth.rate_limit import check_rate_limit

    with patch("api.auth.rate_limit.get_redis") as mock_redis:
        mock_redis.return_value.eval = AsyncMock(return_value=1)
        result = await check_rate_limit("test-key")
    assert result is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_when_exceeded():
    from api.auth.rate_limit import check_rate_limit

    with patch("api.auth.rate_limit.get_redis") as mock_redis:
        mock_redis.return_value.eval = AsyncMock(return_value=0)
        result = await check_rate_limit("test-key")
    assert result is False
