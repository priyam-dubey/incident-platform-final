from app.detector import detect


def pts(n=60, recent=None, base_req=30, base_err=0, p95=100.0):
    rows = [{"requests": base_req, "errors_5xx": base_err if i % 7 else 1, "p95_ms": p95 + (i % 5)} for i in range(n)]
    for i, r in enumerate(recent or []):
        rows[n - len(recent) + i] = r
    return rows


def test_quiet_healthy_app_never_alerts():
    assert detect("a", pts()) == []


def test_error_spike_detected_with_measured_numbers():
    spike = [{"requests": 30, "errors_5xx": 15, "p95_ms": 120.0}] * 5
    d = detect("a", pts(recent=spike))
    assert [x.detector for x in d] == ["error_rate_zscore"]
    assert d[0].severity == "critical" and d[0].details["recent_error_rate"] == 0.5 and d[0].details["z_score"] >= 3


def test_low_traffic_does_not_alert():
    spike = [{"requests": 2, "errors_5xx": 2, "p95_ms": 100.0}] * 5
    assert detect("a", pts(recent=spike)) == []


def test_small_rise_below_threshold_ignored():
    rise = [{"requests": 30, "errors_5xx": 1, "p95_ms": 100.0}] * 5
    assert detect("a", pts(recent=rise)) == []


def test_no_baseline_only_clear_outage_fires():
    few = [{"requests": 0, "errors_5xx": 0, "p95_ms": None}] * 50
    mild = few + [{"requests": 10, "errors_5xx": 3, "p95_ms": 90.0}] * 5
    assert detect("a", mild) == []
    outage = few + [{"requests": 10, "errors_5xx": 9, "p95_ms": 90.0}] * 5
    d = detect("a", outage)
    assert d and d[0].details["baseline"] == "insufficient"


def test_latency_regression_detected():
    slow = [{"requests": 30, "errors_5xx": 0, "p95_ms": 900.0}] * 5
    d = detect("a", pts(recent=slow))
    assert [x.detector for x in d] == ["latency_p95_zscore"] and d[0].severity == "high"


def test_latency_requires_absolute_floor():
    slow = [{"requests": 30, "errors_5xx": 0, "p95_ms": 250.0}] * 5   # 2.5x baseline but under 300 ms
    assert detect("a", pts(recent=slow)) == []


def test_fingerprint_stable_per_app_and_detector():
    spike = [{"requests": 30, "errors_5xx": 15, "p95_ms": 120.0}] * 5
    a1 = detect("a", pts(recent=spike))[0].fingerprint
    assert a1 == detect("a", pts(recent=spike))[0].fingerprint != detect("b", pts(recent=spike))[0].fingerprint
