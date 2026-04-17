"""
api/auth/jwt.py

JWT issue and verification for dashboard (browser) users.
API integrations use API keys (api_keys.py).
Dashboard users authenticate via JWT, issued after they provide
a valid API key through the browser UI.

Tokens are short-lived (1 hour) and carry the API key prefix
so we can identify which key was used without re-hashing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def create_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
) -> str:
    """
    Issue a signed JWT.

    Args:
        subject: Typically the API key prefix (first 12 chars) to identify the key
        extra_claims: Additional payload fields
        expires_minutes: Token lifetime in minutes

    Returns:
        Signed JWT string
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT.

    Returns:
        The decoded payload dict

    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is malformed or signature is invalid
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def verify_token(token: str) -> str | None:
    """
    Convenience wrapper: verify a token and return the subject claim,
    or None if the token is invalid or expired.
    """
    try:
        payload = decode_access_token(token)
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
