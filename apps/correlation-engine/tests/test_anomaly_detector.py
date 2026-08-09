from datetime import datetime, timedelta, timezone

import pytest

from app.anomaly_detector import AnomalyDetector

T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _times(n: int, step_seconds: float = 1.0):
    return [T0 + timedelta(seconds=i * step_seconds) for i in range(n)]


def test_returns_none_during_cold_start_before_min_samples() -> None:
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=60, min_samples=5)
    times = _times(4)
    for t in times:
        result = detector.observe("checkout-api", "latency_ms", 100.0, t)
        assert result is None  # fewer than min_samples observed so far


def test_detects_obvious_spike_after_stable_baseline() -> None:
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=60, min_samples=10)
    times = _times(21)

    for t in times[:20]:
        result = detector.observe("checkout-api", "latency_ms", 100.0, t)
        assert result is None  # stable baseline, no variance -> no anomaly signal yet

    spike = detector.observe("checkout-api", "latency_ms", 5000.0, times[20])
    assert spike is not None
    assert spike.service_name == "checkout-api"
    assert spike.metric_name == "latency_ms"
    assert spike.observed_value == 5000.0
    assert spike.zscore == float("inf")  # zero-variance baseline, any deviation is maximal


def test_does_not_flag_values_within_normal_variance() -> None:
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=60, min_samples=10)
    times = _times(15)
    values = [98, 101, 99, 102, 100, 97, 103, 100, 99, 101, 100, 98, 102, 101, 100]

    results = [detector.observe("checkout-api", "latency_ms", v, t) for v, t in zip(values, times)]
    assert all(r is None for r in results)


def test_metrics_are_isolated_per_service_and_metric_name() -> None:
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=60, min_samples=3)
    times = _times(4)

    for t in times[:3]:
        detector.observe("checkout-api", "latency_ms", 100.0, t)
        detector.observe("checkout-api", "error_rate", 0.01, t)
        detector.observe("payments-api", "latency_ms", 100.0, t)

    # A spike in checkout-api/latency_ms must not affect other (service, metric) pairs.
    spike = detector.observe("checkout-api", "latency_ms", 9999.0, times[3])
    unaffected_metric = detector.observe("checkout-api", "error_rate", 0.01, times[3])
    unaffected_service = detector.observe("payments-api", "latency_ms", 100.0, times[3])

    assert spike is not None
    assert unaffected_metric is None
    assert unaffected_service is None


def test_baseline_adapts_to_sustained_regime_shift() -> None:
    # A sustained shift to a new (still stable) level should eventually stop
    # triggering as the window fills with the new normal - anomaly detection
    # that never adapts would alert forever on a legitimate traffic change.
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=10, min_samples=5)
    times = _times(20)

    for t in times[:10]:
        detector.observe("checkout-api", "rps", 100.0, t)

    # Shift to a new sustained level of 200 rps.
    first_shift_result = detector.observe("checkout-api", "rps", 200.0, times[10])
    assert first_shift_result is not None  # the shift itself is flagged

    last_result = None
    for t in times[11:20]:
        last_result = detector.observe("checkout-api", "rps", 200.0, t)

    # Once the window (size 10) is filled with the new level, it reads as stable again.
    assert last_result is None


def test_sample_count_tracks_observations_up_to_window_size() -> None:
    detector = AnomalyDetector(zscore_threshold=3.0, window_size=5, min_samples=2)
    times = _times(8)
    for t in times:
        detector.observe("checkout-api", "latency_ms", 100.0, t)

    assert detector.sample_count("checkout-api", "latency_ms") == 5  # capped at window_size
    assert detector.sample_count("unknown-service", "latency_ms") == 0


def test_rejects_invalid_construction_params() -> None:
    with pytest.raises(ValueError):
        AnomalyDetector(zscore_threshold=0)
    with pytest.raises(ValueError):
        AnomalyDetector(window_size=1)
    with pytest.raises(ValueError):
        AnomalyDetector(min_samples=1)


def test_anomaly_score_is_always_positive_regardless_of_direction() -> None:
    detector = AnomalyDetector(zscore_threshold=2.0, window_size=60, min_samples=5)
    times = _times(10)
    values = [100, 101, 99, 100, 101]
    for v, t in zip(values, times[:5]):
        detector.observe("checkout-api", "success_rate", v, t)

    # A sharp *drop* should also register as anomalous (negative z-score),
    # and anomaly_score should report it as a positive magnitude.
    drop = detector.observe("checkout-api", "success_rate", 10.0, times[5])
    assert drop is not None
    assert drop.zscore < 0
    assert drop.anomaly_score > 0
    assert drop.anomaly_score == abs(drop.zscore)
