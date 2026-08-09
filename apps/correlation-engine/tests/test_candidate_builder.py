import uuid
from datetime import datetime, timedelta, timezone

from app.anomaly_detector import AnomalyResult
from app.candidate_builder import build_incident_candidate
from app.cluster_engine import AnomalyCluster
from app.evidence_buffer import EvidenceBuffer
from incident_schemas import IncidentSeverity, LogEvent

T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)
WORKSPACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _anomaly(service: str, score: float = 5.0, offset_seconds: float = 0) -> AnomalyResult:
    return AnomalyResult(
        service_name=service,
        metric_name="error_rate",
        observed_value=0.4,
        baseline_mean=0.01,
        baseline_stddev=0.02,
        zscore=score,
        occurred_at=T0 + timedelta(seconds=offset_seconds),
    )


def _log_event(service: str, offset_seconds: float, severity: str = "error") -> LogEvent:
    return LogEvent(
        workspace_id=WORKSPACE_ID,
        service_name=service,
        timestamp=(T0 + timedelta(seconds=offset_seconds)).isoformat(),
        severity=severity,
        message=f"downstream timeout in {service}",
    )


def test_builds_valid_candidate_with_buffered_evidence() -> None:
    cluster = AnomalyCluster(anomalies=[_anomaly("checkout-api", score=5.0, offset_seconds=10)])
    buffer = EvidenceBuffer()
    buffer.add_log(_log_event("checkout-api", offset_seconds=10))

    service_ids = {"checkout-api": uuid.uuid4()}
    candidate = build_incident_candidate(
        workspace_id=WORKSPACE_ID,
        cluster=cluster,
        evidence_buffer=buffer,
        service_ids=service_ids,
        detected_at=T0 + timedelta(seconds=15),
    )

    assert candidate.workspace_id == WORKSPACE_ID
    assert len(candidate.affected_services) == 1
    assert candidate.affected_services[0].service_name == "checkout-api"
    assert len(candidate.evidence) == 1
    assert "downstream timeout" in candidate.evidence[0].snippet


def test_synthesizes_fallback_evidence_when_buffer_is_empty() -> None:
    # No logs/traces buffered at all - must still produce a schema-valid
    # candidate (evidence is a required, non-empty field) using the anomaly
    # itself as evidence rather than silently dropping the incident.
    cluster = AnomalyCluster(anomalies=[_anomaly("checkout-api", score=7.0, offset_seconds=0)])
    buffer = EvidenceBuffer()  # empty

    candidate = build_incident_candidate(
        workspace_id=WORKSPACE_ID,
        cluster=cluster,
        evidence_buffer=buffer,
        service_ids={"checkout-api": uuid.uuid4()},
        detected_at=T0,
    )

    assert len(candidate.evidence) == 1
    assert candidate.evidence[0].source_type == "metric"
    assert "error_rate" in candidate.evidence[0].snippet


def test_severity_escalates_with_max_anomaly_score() -> None:
    buffer = EvidenceBuffer()
    service_ids = {"checkout-api": uuid.uuid4()}

    low = build_incident_candidate(
        WORKSPACE_ID,
        AnomalyCluster(anomalies=[_anomaly("checkout-api", score=3.2)]),
        buffer,
        service_ids,
        T0,
    )
    high = build_incident_candidate(
        WORKSPACE_ID,
        AnomalyCluster(anomalies=[_anomaly("checkout-api", score=7.5)]),
        buffer,
        service_ids,
        T0,
    )
    critical = build_incident_candidate(
        WORKSPACE_ID,
        AnomalyCluster(anomalies=[_anomaly("checkout-api", score=15.0)]),
        buffer,
        service_ids,
        T0,
    )

    assert low.suggested_severity == IncidentSeverity.low
    assert high.suggested_severity == IncidentSeverity.high
    assert critical.suggested_severity == IncidentSeverity.critical


def test_evidence_from_multiple_services_in_cluster_is_included() -> None:
    cluster = AnomalyCluster(
        anomalies=[
            _anomaly("checkout-api", offset_seconds=0),
            _anomaly("payments-api", offset_seconds=20),
        ]
    )
    buffer = EvidenceBuffer()
    buffer.add_log(_log_event("checkout-api", offset_seconds=0))
    buffer.add_log(_log_event("payments-api", offset_seconds=20))

    service_ids = {"checkout-api": uuid.uuid4(), "payments-api": uuid.uuid4()}
    candidate = build_incident_candidate(WORKSPACE_ID, cluster, buffer, service_ids, T0)

    services_with_evidence = {e.service_name for e in candidate.evidence}
    assert services_with_evidence == {"checkout-api", "payments-api"}


def test_candidate_window_is_valid_against_schema_constraints() -> None:
    # This is really testing that build_incident_candidate's window padding
    # doesn't collide with IncidentCandidate's own evidence-window validator.
    cluster = AnomalyCluster(
        anomalies=[
            _anomaly("checkout-api", offset_seconds=0),
            _anomaly("checkout-api", offset_seconds=59),
        ]
    )
    buffer = EvidenceBuffer()
    buffer.add_log(_log_event("checkout-api", offset_seconds=0))
    buffer.add_log(_log_event("checkout-api", offset_seconds=59))

    candidate = build_incident_candidate(
        WORKSPACE_ID, cluster, buffer, {"checkout-api": uuid.uuid4()}, T0
    )
    assert candidate.window_start <= candidate.window_end
    for item in candidate.evidence:
        assert candidate.window_start <= item.occurred_at <= candidate.window_end
