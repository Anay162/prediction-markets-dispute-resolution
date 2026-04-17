"""
api/auth/rate_limit.py

Per-API-key token bucket rate limiter backed by Redis.

Uses a sliding window counter: each key gets a bucket of N tokens
per minute. A Lua script handles the check-and-decrement atomically.
"""

from __future__ import annotations

import hashlib
import os
import time

from data.cache.redis_client import get_redis

RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60"))

# Lua script for atomic check-and-decrement
# Returns 1 if the request is allowed, 0 if rate limited
_RATE_LIMIT_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Remove entries outside the current window
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Count current entries
local count = redis.call('ZCARD', key)

if count < limit then
    -- Add this request
    redis.call('ZADD', key, now, now .. math.random())
    redis.call('EXPIRE', key, window + 1)
    return 1
else
    return 0
end
"""


async def check_rate_limit(api_key: str) -> bool:
    """
    Check and consume one token from the rate limit bucket for api_key.
    Returns True if the request is allowed, False if rate limited.
    """
    redis = get_redis()
    bucket_key = f"ratelimit:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    now_ms = int(time.time() * 1000)
    window_ms = 60_000  # 1 minute in milliseconds

    result = await redis.eval(
        _RATE_LIMIT_LUA,
        1,  # Number of keys
        bucket_key,  # KEYS[1]
        RATE_LIMIT_RPM,  # ARGV[1]: max requests
        window_ms,  # ARGV[2]: window in ms
        now_ms,  # ARGV[3]: current time in ms
    )
    return bool(result)


async def get_rate_limit_status(api_key: str) -> dict:
    """Return current rate limit usage for an API key."""
    redis = get_redis()
    bucket_key = f"ratelimit:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    now_ms = int(time.time() * 1000)
    window_ms = 60_000

    await redis.zremrangebyscore(bucket_key, 0, now_ms - window_ms)
    count = await redis.zcard(bucket_key)

    return {
        "limit": RATE_LIMIT_RPM,
        "remaining": max(0, RATE_LIMIT_RPM - count),
        "used": count,
        "window_seconds": 60,
    }
