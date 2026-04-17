"""
api/routers/health.py

Health and readiness probes for Kubernetes and load balancer checks.

    GET /health   Liveness probe — is the process alive?
    GET /ready    Readiness probe — can the app serve traffic?
                  Checks DB and Redis connectivity.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health", include_in_schema=False)
async def health():
    """Liveness probe. Always returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready():
    """
    Readiness probe. Checks that the database and Redis are reachable.
    Returns 200 if ready, 503 if any dependency is unavailable.
    """
    checks: dict[str, str] = {}
    all_ok = True

    # Check database
    try:
        from data.database import get_session
        from sqlalchemy import text
        async with get_session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        all_ok = False

    # Check Redis
    try:
        from data.cache.redis_client import get_redis
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        all_ok = False

    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ok else "unavailable", "checks": checks},
    )
