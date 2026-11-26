"""Deterministic incident detection on real application telemetry.

No AI is involved here. Detection compares a short *recent* window against a
rolling *baseline* from the same application (z-score on per-bucket values) and
requires minimum traffic, so a quiet application does not alert on noise.
Every number placed on an incident comes from these measurements.
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass, field
from typing import Any

RECENT_BUCKETS = 5            # most recent buckets (5 minutes at 60 s buckets)
MIN_BASELINE_BUCKETS = 10     # buckets with traffic needed to trust a baseline
MIN_RECENT_REQUESTS = 20
Z_THRESHOLD = 3.0
MIN_ERROR_RATE = 0.05
STD_FLOOR_RATE = 0.02
LATENCY_MIN_MS = 300.0
LATENCY_RATIO = 2.0
NO_BASELINE_ERROR_RATE = 0.5   # without a baseline, only a clear outage fires


@dataclass
class Detection:
    detector: str
    severity: str
    title: str
    fingerprint: str
    details: dict[str, Any] = field(default_factory=dict)


def _fp(application_id: str, detector: str) -> str:
    return hashlib.sha256(f"{application_id}:{detector}".encode()).hexdigest()[:32]


def _split(points: list[dict]) -> tuple[list[dict], list[dict]]:
    return points[:-RECENT_BUCKETS], points[-RECENT_BUCKETS:]


def detect(application_id: str, points: list[dict]) -> list[Detection]:
    """`points` is the gap-filled series from telemetry_queries.shape_timeseries()['points'] (oldest first)."""
    if len(points) <= RECENT_BUCKETS:
        return []
    baseline, recent = _split(points)
    out: list[Detection] = []
    out += _error_rate(application_id, baseline, recent)
    out += _latency(application_id, baseline, recent)
    return out


def _zscore(value: float, sample: list[float], floor: float) -> tuple[float, float, float]:
    mean = statistics.fmean(sample)
    std = max(statistics.pstdev(sample) if len(sample) > 1 else 0.0, floor)
    return (value - mean) / std, mean, std


def _error_rate(app_id: str, baseline: list[dict], recent: list[dict]) -> list[Detection]:
    req = sum(p["requests"] for p in recent)
    err = sum(p["errors_5xx"] for p in recent)
    if req < MIN_RECENT_REQUESTS:
        return []
    rate = err / req
    rates = [p["errors_5xx"] / p["requests"] for p in baseline if p["requests"] > 0]
    details: dict[str, Any] = {"recent_requests": req, "recent_errors_5xx": err, "recent_error_rate": round(rate, 4),
                               "recent_window_buckets": len(recent), "baseline_buckets_with_traffic": len(rates)}
    if len(rates) >= MIN_BASELINE_BUCKETS:
        z, mean, std = _zscore(rate, rates, STD_FLOOR_RATE)
        details.update(baseline_mean_error_rate=round(mean, 4), baseline_std=round(std, 4), z_score=round(z, 2), baseline="ok")
        if rate < MIN_ERROR_RATE or z < Z_THRESHOLD:
            return []
    else:
        details.update(baseline="insufficient", note="Not enough history for a baseline; only a clear outage is reported.")
        if rate < NO_BASELINE_ERROR_RATE:
            return []
    severity = "critical" if rate >= 0.5 else "high" if rate >= 0.2 else "medium"
    return [Detection("error_rate_zscore", severity, f"5xx error rate at {rate:.0%} ({err} of {req} requests)",
                      _fp(app_id, "error_rate_zscore"), details)]


def _latency(app_id: str, baseline: list[dict], recent: list[dict]) -> list[Detection]:
    live = [p for p in recent if p["requests"] > 0 and p["p95_ms"] is not None]
    req = sum(p["requests"] for p in live)
    if req < MIN_RECENT_REQUESTS:
        return []
    recent_p95 = sum(p["p95_ms"] * p["requests"] for p in live) / req      # request-weighted
    sample = [p["p95_ms"] for p in baseline if p["requests"] > 0 and p["p95_ms"] is not None]
    if len(sample) < MIN_BASELINE_BUCKETS:
        return []                                                       # latency needs a real baseline
    z, mean, std = _zscore(recent_p95, sample, max(10.0, 0.05 * statistics.fmean(sample)))
    if recent_p95 < LATENCY_MIN_MS or recent_p95 < LATENCY_RATIO * mean or z < Z_THRESHOLD:
        return []
    ratio = recent_p95 / mean if mean else float("inf")
    return [Detection("latency_p95_zscore", "high" if ratio >= 5 else "medium",
                      f"p95 latency {recent_p95:.0f} ms ({ratio:.1f}x baseline {mean:.0f} ms)", _fp(app_id, "latency_p95_zscore"),
                      {"recent_requests": req, "recent_p95_ms": round(recent_p95, 1), "baseline_mean_p95_ms": round(mean, 1),
                       "baseline_std_ms": round(std, 1), "z_score": round(z, 2), "baseline_buckets_with_traffic": len(sample)})]
