"""
Token-bucket rate limiting, keyed per API key.

This implementation is in-process (a dict of buckets), which is correct for
a single ingestion-service replica but not for N replicas behind a load
balancer, where each replica would enforce the limit independently and the
effective limit becomes N x the configured value. The fix at that point is a
one-line swap: replace TokenBucketLimiter with a Redis-backed implementation
using the same `allow(key) -> bool` interface (Lua script doing the
check-and-decrement atomically, exactly the pattern used in Project 1's
quota-decision service) - nothing calling this class needs to change.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    def __init__(self, rate_per_second: float, burst: int) -> None:
        if rate_per_second <= 0 or burst <= 0:
            raise ValueError("rate_per_second and burst must be positive")
        self._rate = rate_per_second
        self._burst = burst
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int = 1) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self._burst), last_refill=now)
                self._buckets[key] = bucket

            elapsed = now - bucket.last_refill
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
            bucket.last_refill = now

            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True
            return False
