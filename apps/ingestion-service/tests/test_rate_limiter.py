import time

import pytest

from app.rate_limiter import TokenBucketLimiter


def test_allows_requests_within_burst() -> None:
    limiter = TokenBucketLimiter(rate_per_second=10, burst=5)
    for _ in range(5):
        assert limiter.allow("key-a") is True


def test_rejects_once_burst_is_exhausted() -> None:
    limiter = TokenBucketLimiter(rate_per_second=1, burst=3)
    for _ in range(3):
        assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is False


def test_different_keys_have_independent_buckets() -> None:
    limiter = TokenBucketLimiter(rate_per_second=1, burst=1)
    assert limiter.allow("key-a") is True
    assert limiter.allow("key-b") is True  # independent bucket, not shared


def test_tokens_refill_over_time() -> None:
    limiter = TokenBucketLimiter(rate_per_second=1000, burst=1)
    assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is False
    time.sleep(0.01)  # 1000/s * 0.01s = ~10 tokens refilled, well over cost of 1
    assert limiter.allow("key-a") is True


def test_cost_greater_than_one_consumes_multiple_tokens() -> None:
    limiter = TokenBucketLimiter(rate_per_second=1, burst=10)
    assert limiter.allow("key-a", cost=7) is True
    assert limiter.allow("key-a", cost=4) is False  # only 3 tokens left
    assert limiter.allow("key-a", cost=3) is True


def test_rejects_invalid_construction_params() -> None:
    with pytest.raises(ValueError):
        TokenBucketLimiter(rate_per_second=0, burst=5)
    with pytest.raises(ValueError):
        TokenBucketLimiter(rate_per_second=5, burst=0)
