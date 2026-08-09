import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.anomaly_detector import AnomalyDetector
from app.cluster_engine import ClusterEngine
from app.evidence_buffer import EvidenceBuffer
from app.pipeline import CorrelationPipeline
from incident_schemas import LogEvent, MetricEvent

WORKSPACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _metric(service: str, metric: str, value: float, offset_seconds: float) -> MetricEvent:
    return MetricEvent(
        workspace_id=WORKSPACE_ID,
        service_name=service,
        timestamp=(T0 + timedelta(seconds=offset_seconds)).isoformat(),
        metric_name=metric,
        value=value,
    )


def _log(service: str, offset_seconds: float, message: str = "downstream timeout") -> LogEvent:
    return LogEvent(
        workspace_id=WORKSPACE_ID,
        service_name=service,
        timestamp=(T0 + timedelta(seconds=offset_seconds)).isoformat(),
        severity="error",
        message=message,
    )


@pytest.fixture
def pipeline(fake_service_registry, fake_candidate_sink) -> CorrelationPipeline:
    return CorrelationPipeline(
        anomaly_detector=AnomalyDetector(zscore_threshold=3.0, window_size=60, min_samples=10),
        cluster_engine=ClusterEngine(correlation_window_seconds=60),
        evidence_buffer=EvidenceBuffer(),
        service_registry=fake_service_registry,
        candidate_sink=fake_candidate_sink,
        correlation_window_seconds=60,
    )


async def _warm_up_baseline(pipeline: CorrelationPipeline, service: str, metric: str, value: float) -> None:
    for i in range(15):
        await pipeline.handle_metric_event(_metric(service, metric, value, offset_seconds=i))


async def test_no_candidates_emitted_when_nothing_anomalous(pipeline: CorrelationPipeline) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    emitted = await pipeline.tick(T0 + timedelta(seconds=20))
    assert emitted == []


async def test_single_service_spike_produces_one_candidate(
    pipeline: CorrelationPipeline, fake_candidate_sink
) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    await pipeline.handle_log_event(_log("checkout-api", offset_seconds=16))
    await pipeline.handle_metric_event(_metric("checkout-api", "latency_ms", 9000.0, offset_seconds=16))

    emitted = await pipeline.tick(T0 + timedelta(seconds=20))

    assert len(emitted) == 1
    assert emitted[0].affected_services[0].service_name == "checkout-api"
    assert len(fake_candidate_sink.published) == 1


async def test_correlated_spikes_across_services_merge_into_one_candidate(
    pipeline: CorrelationPipeline,
) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    await _warm_up_baseline(pipeline, "payments-api", "latency_ms", 100.0)

    await pipeline.handle_metric_event(_metric("checkout-api", "latency_ms", 9000.0, offset_seconds=16))
    await pipeline.handle_metric_event(_metric("payments-api", "latency_ms", 9500.0, offset_seconds=18))

    emitted = await pipeline.tick(T0 + timedelta(seconds=20))

    assert len(emitted) == 1
    assert {s.service_name for s in emitted[0].affected_services} == {"checkout-api", "payments-api"}


async def test_pending_anomalies_are_cleared_after_tick(pipeline: CorrelationPipeline) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    await pipeline.handle_metric_event(_metric("checkout-api", "latency_ms", 9000.0, offset_seconds=16))

    first_tick = await pipeline.tick(T0 + timedelta(seconds=20))
    second_tick = await pipeline.tick(T0 + timedelta(seconds=40))

    assert len(first_tick) == 1
    assert second_tick == []  # nothing new happened between ticks


async def test_evidence_is_attached_from_buffered_log_events(pipeline: CorrelationPipeline) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    await pipeline.handle_log_event(_log("checkout-api", offset_seconds=16, message="pool exhausted"))
    await pipeline.handle_metric_event(_metric("checkout-api", "latency_ms", 9000.0, offset_seconds=16))

    emitted = await pipeline.tick(T0 + timedelta(seconds=20))

    assert len(emitted) == 1
    snippets = [e.snippet for e in emitted[0].evidence]
    assert any("pool exhausted" in s for s in snippets)


async def test_service_ids_are_resolved_via_registry(
    pipeline: CorrelationPipeline, fake_service_registry
) -> None:
    await _warm_up_baseline(pipeline, "checkout-api", "latency_ms", 100.0)
    await pipeline.handle_metric_event(_metric("checkout-api", "latency_ms", 9000.0, offset_seconds=16))

    emitted = await pipeline.tick(T0 + timedelta(seconds=20))

    expected_id = await fake_service_registry.resolve(WORKSPACE_ID, "checkout-api")
    assert emitted[0].affected_services[0].service_id == expected_id
