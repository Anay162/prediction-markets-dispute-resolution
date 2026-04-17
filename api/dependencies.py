"""
api/dependencies.py

Shared FastAPI dependencies injected into route handlers.
Centralises auth, database session, and rate limiting logic.
"""
from __future__ import annotations

import hashlib
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from data.database import get_db

# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_MASTER_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")


async def require_api_key(
    api_key: str | None = Security(API_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    Validates the X-API-Key header.
    In production this checks the api_keys table.
    In development the master key from env is accepted directly.
    Returns the raw API key string on success.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Dev shortcut: accept the master key directly
    if api_key == _MASTER_KEY:
        return api_key

    # Production: check the hashed key in the database
    from api.auth.api_keys import verify_api_key
    key_record = await verify_api_key(db, api_key)
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key


async def require_api_key_with_rate_limit(
    api_key: str = Depends(require_api_key),
) -> str:
    """
    Like require_api_key but also checks the per-key rate limit.
    """
    from api.auth.rate_limit import check_rate_limit
    allowed = await check_rate_limit(api_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Default: 60 requests/minute per API key.",
            headers={"Retry-After": "60"},
        )
    return api_key


# ---------------------------------------------------------------------------
# Convenience type aliases for route signatures
# ---------------------------------------------------------------------------

AuthDep = Annotated[str, Depends(require_api_key_with_rate_limit)]
DBDep = Annotated[AsyncSession, Depends(get_db)]
