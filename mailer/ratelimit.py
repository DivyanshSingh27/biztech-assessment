"""Sliding-window rate limiter backed by a Redis sorted set.

All workers share one sorted set. A Lua script runs the whole
check-and-record sequence atomically inside Redis, so concurrent
workers cannot exceed the limit together.
"""
import uuid

import redis
from django.conf import settings

SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local member_id = ARGV[3]

-- Use Redis' own clock so workers with different system clocks agree.
local t = redis.call('TIME')
local now_ms = t[1] * 1000 + math.floor(t[2] / 1000)

-- 1. Drop entries that fell out of the window.
redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)

-- 2. Count what is left inside the window.
local count = redis.call('ZCARD', key)

-- 3a. Room left: record this send and allow it.
if count < limit then
  redis.call('ZADD', key, now_ms, member_id)
  redis.call('PEXPIRE', key, window_ms)
  return {1, 0}
end

-- 3b. Full: tell the caller when the oldest entry leaves the window.
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry_after_ms = tonumber(oldest[2]) + window_ms - now_ms
if retry_after_ms < 1 then
  retry_after_ms = 1
end
return {0, retry_after_ms}
"""


class SlidingWindowRateLimiter:
    def __init__(self, client, key, limit, window_seconds):
        self.client = client
        self.key = key
        self.limit = limit
        self.window_ms = int(window_seconds * 1000)
        self._script = client.register_script(SLIDING_WINDOW_LUA)

    def acquire(self):
        """Try to take one slot. Returns (allowed, retry_after_ms)."""
        allowed, retry_after_ms = self._script(
            keys=[self.key],
            args=[self.limit, self.window_ms, uuid.uuid4().hex],
        )
        return bool(allowed), int(retry_after_ms)


def get_email_rate_limiter():
    client = redis.Redis.from_url(settings.REDIS_URL)
    return SlidingWindowRateLimiter(
        client,
        key="ratelimit:email",
        limit=settings.EMAIL_RATE_LIMIT,
        window_seconds=settings.EMAIL_RATE_WINDOW_SECONDS,
    )
