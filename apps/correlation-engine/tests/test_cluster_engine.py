from datetime import datetime, timedelta, timezone

import pytest

from app.anomaly_detector import AnomalyResult
from app.cluster_engine import ClusterEngine

T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _anomaly(service: str, metric: str = "latency_ms", score: float = 4.0, offset_seconds: float = 0) -> AnomalyResult:
    return AnomalyResult(
        service_name=service,
        metric_name=metric,
        observed_value=999.0,
        baseline_mean=100.0,
        baseline_stddev=10.0,
        zscore=score,
        occurred_at=T0 + timedelta(seconds=offset_seconds),
    )


def test_empty_input_returns_no_clusters() -> None:
    engine = ClusterEngine(correlation_window_seconds=60)
    assert engine.cluster([]) == []


def test_single_anomaly_forms_its_own_cluster() -> None:
    engine = ClusterEngine(correlation_window_seconds=60)
    clusters = engine.cluster([_anomaly("checkout-api")])
    assert len(clusters) == 1
    assert clusters[0].service_names == {"checkout-api"}


def test_anomalies_within_window_are_merged_into_one_cluster() -> None:
    engine = ClusterEngine(correlation_window_seconds=60)
    anomalies = [
        _anomaly("checkout-api", offset_seconds=0),
        _anomaly("payments-api", offset_seconds=20),
        _anomaly("inventory-api", offset_seconds=45),
    ]
    clusters = engine.cluster(anomalies)
    assert len(clusters) == 1
    assert clusters[0].service_names == {"checkout-api", "payments-api", "inventory-api"}


def test_anomalies_outside_window_form_separate_clusters() -> None:
    engine = ClusterEngine(correlation_window_seconds=30)
    anomalies = [
        _anomaly("checkout-api", offset_seconds=0),
        _anomaly("payments-api", offset_seconds=500),  # far outside window, no trace link either
    ]
    clusters = engine.cluster(anomalies)
    assert len(clusters) == 2
    assert {frozenset(c.service_names) for c in clusters} == {
        frozenset({"checkout-api"}),
        frozenset({"payments-api"}),
    }


def test_transitive_clustering_via_chained_temporal_overlap() -> None:
    # A and B are within window of each other; B and C are within window of
    # each other; A and C are NOT directly within window. Union-find must
    # still merge all three via the B bridge (transitivity).
    engine = ClusterEngine(correlation_window_seconds=30)
    anomalies = [
        _anomaly("service-a", offset_seconds=0),
        _anomaly("service-b", offset_seconds=25),
        _anomaly("service-c", offset_seconds=50),
    ]
    clusters = engine.cluster(anomalies)
    assert len(clusters) == 1
    assert clusters[0].service_names == {"service-a", "service-b", "service-c"}


def test_shared_trace_id_links_temporally_distant_anomalies() -> None:
    # Far apart in time (outside the correlation window) but linked by a
    # shared trace - a slow downstream call whose effect surfaces late.
    engine = ClusterEngine(correlation_window_seconds=10)
    anomalies = [
        _anomaly("checkout-api", offset_seconds=0),
        _anomaly("payments-api", offset_seconds=300),
    ]
    trace_links = {"trace-xyz": {"checkout-api", "payments-api"}}

    clusters = engine.cluster(anomalies, trace_links=trace_links)
    assert len(clusters) == 1
    assert clusters[0].service_names == {"checkout-api", "payments-api"}
    assert "trace-xyz" in clusters[0].linked_trace_ids


def test_clusters_sorted_by_max_anomaly_score_descending() -> None:
    engine = ClusterEngine(correlation_window_seconds=5)
    anomalies = [
        _anomaly("low-severity-service", score=3.1, offset_seconds=0),
        _anomaly("high-severity-service", score=9.5, offset_seconds=1000),
    ]
    clusters = engine.cluster(anomalies)
    assert len(clusters) == 2
    assert clusters[0].service_names == {"high-severity-service"}
    assert clusters[1].service_names == {"low-severity-service"}


def test_cluster_window_start_and_end_reflect_member_anomalies() -> None:
    engine = ClusterEngine(correlation_window_seconds=60)
    anomalies = [
        _anomaly("checkout-api", offset_seconds=0),
        _anomaly("payments-api", offset_seconds=45),
    ]
    clusters = engine.cluster(anomalies)
    assert clusters[0].window_start == T0
    assert clusters[0].window_end == T0 + timedelta(seconds=45)


def test_rejects_non_positive_correlation_window() -> None:
    with pytest.raises(ValueError):
        ClusterEngine(correlation_window_seconds=0)
