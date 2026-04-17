"""
data/cache/redis_client.py

Async Redis client and simple get/set/delete helpers used by the
report cache and source probe cache.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def init_redis(redis_url: str) -> None:
    """Initialise the Redis client. Called once at startup."""
    global _redis
    _redis = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    logger.info("Redis client initialised")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() at startup.")
    return _redis


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """Store a JSON-serialisable value with a TTL."""
    try:
        await get_redis().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:
        logger.warning(f"Cache set failed for key '{key}': {e}")


async def cache_get(key: str) -> Any | None:
    """Retrieve a cached value. Returns None on miss or error."""
    try:
        raw = await get_redis().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Cache get failed for key '{key}': {e}")
        return None


async def cache_delete(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception as e:
        logger.warning(f"Cache delete failed for key '{key}': {e}")


async def job_set_status(job_id: str, status_data: dict, ttl_seconds: int = 86400) -> None:
    """Store async job status. TTL default is 24h."""
    await cache_set(f"job:{job_id}:status", status_data, ttl_seconds)


async def job_get_status(job_id: str) -> dict | None:
    return await cache_get(f"job:{job_id}:status")


async def job_update_progress(job_id: str, stage: str, pct: int) -> None:
    """
    Update just the progress fields of an existing job status entry.
    Used by the pipeline's progress_callback.
    """
    existing = await job_get_status(job_id) or {}
    existing.update({"current_stage": stage, "progress_pct": pct, "status": "running"})
    await job_set_status(job_id, existing)
