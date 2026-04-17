"""
api/auth/api_keys.py

API key management: creation, hashing, and verification.

Keys are stored hashed (SHA-256) in the api_keys table.
The raw key is shown once on creation and never stored.
Format: "ca_live_<32 random hex chars>"
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data.models.api_key import APIKey

KEY_PREFIX_LIVE = "ca_live_"
KEY_PREFIX_TEST = "ca_test_"
SALT = os.getenv("API_KEY_SALT", "dev-salt-change-me")


def generate_api_key(test: bool = False) -> str:
    """Generate a new raw API key. Never stored — shown once to the user."""
    prefix = KEY_PREFIX_TEST if test else KEY_PREFIX_LIVE
    return prefix + secrets.token_hex(32)


def hash_api_key(raw_key: str) -> str:
    """Deterministic SHA-256 hash of a raw key + salt."""
    return hashlib.sha256(f"{SALT}:{raw_key}".encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    name: str,
    test: bool = False,
) -> tuple[str, APIKey]:
    """
    Create a new API key record.
    Returns (raw_key, APIKey ORM object).
    raw_key is the only time the unhashed key is available.
    """
    raw = generate_api_key(test=test)
    key_hash = hash_api_key(raw)

    record = APIKey(
        id=uuid.uuid4(),
        name=name,
        key_hash=key_hash,
        key_prefix=raw[:12],  # Store first 12 chars so users can identify their key
        is_test=test,
        is_active=True,
        created_at=datetime.utcnow(),
        last_used_at=None,
        request_count=0,
    )
    db.add(record)
    await db.flush()
    return raw, record


async def verify_api_key(db: AsyncSession, raw_key: str) -> APIKey | None:
    """
    Verify a raw API key against the database.
    Updates last_used_at and request_count on success.
    Returns the APIKey ORM object if valid, None otherwise.
    """
    key_hash = hash_api_key(raw_key)
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,
        )
    )
    record = result.scalar_one_or_none()
    if record:
        record.last_used_at = datetime.utcnow()
        record.request_count = (record.request_count or 0) + 1
    return record


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID) -> bool:
    """Deactivate an API key. Returns True if found and deactivated."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    record = result.scalar_one_or_none()
    if not record:
        return False
    record.is_active = False
    return True
