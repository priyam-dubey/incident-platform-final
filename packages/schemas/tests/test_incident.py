import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from incident_schemas import EvidenceItem, IncidentCandidate, ServiceAnomaly  # noqa: E402

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
SERVICE_ID = "22222222-2222-2222-2222-222222222222"
INCIDENT_ID = "33333333-3333-3333-3333-333333333333"
EVIDENCE_ID = "44444444-4444-4444-4444-444444444444"


def _anomaly() -> dict:
    return dict(
        service_id=SERVICE_ID,
        service_name="checkout-api",
        anomaly_score=4.2,
        metric_name="error_rate",
        observed_value=0.18,
        baseline_mean=0.01,
        baseline_stddev=0.004,
    )


def _evidence(occurred_at: str) -> dict:
    return dict(
        id=EVIDENCE_ID,
        source_type="log",
        source_ref="clickhouse://logs/abc123",
        service_name="checkout-api",
        snippet="connection timeout after 30000ms",
        relevance_score=0.9,
        occurred_at=occurred_at,
    )


def test_incident_candidate_accepts_evidence_within_window() -> None:
    candidate = IncidentCandidate(
        id=INCIDENT_ID,
        workspace_id=WORKSPACE_ID,
        detected_at="2026-08-05T10:05:00Z",
        window_start="2026-08-05T10:00:00Z",
        window_end="2026-08-05T10:05:00Z",
        affected_services=[ServiceAnomaly(**_anomaly())],
        evidence=[EvidenceItem(**_evidence("2026-08-05T10:02:30Z"))],
        suggested_severity="high",
    )
    assert candidate.suggested_severity.value == "high"


def test_incident_candidate_rejects_evidence_outside_window() -> None:
    with pytest.raises(ValidationError, match="outside incident window"):
        IncidentCandidate(
            id=INCIDENT_ID,
            workspace_id=WORKSPACE_ID,
            detected_at="2026-08-05T10:05:00Z",
            window_start="2026-08-05T10:00:00Z",
            window_end="2026-08-05T10:05:00Z",
            affected_services=[ServiceAnomaly(**_anomaly())],
            evidence=[EvidenceItem(**_evidence("2026-08-05T09:00:00Z"))],
            suggested_severity="high",
        )


def test_incident_candidate_allows_small_clock_skew_grace_period() -> None:
    # 3 seconds before window_start - within the 5s grace period.
    candidate = IncidentCandidate(
        id=INCIDENT_ID,
        workspace_id=WORKSPACE_ID,
        detected_at="2026-08-05T10:05:00Z",
        window_start="2026-08-05T10:00:00Z",
        window_end="2026-08-05T10:05:00Z",
        affected_services=[ServiceAnomaly(**_anomaly())],
        evidence=[EvidenceItem(**_evidence("2026-08-05T09:59:57Z"))],
        suggested_severity="medium",
    )
    assert len(candidate.evidence) == 1


def test_incident_candidate_rejects_inverted_window() -> None:
    with pytest.raises(ValidationError, match="window_end must not be before"):
        IncidentCandidate(
            id=INCIDENT_ID,
            workspace_id=WORKSPACE_ID,
            detected_at="2026-08-05T10:05:00Z",
            window_start="2026-08-05T10:05:00Z",
            window_end="2026-08-05T10:00:00Z",
            affected_services=[ServiceAnomaly(**_anomaly())],
            evidence=[EvidenceItem(**_evidence("2026-08-05T10:02:00Z"))],
            suggested_severity="low",
        )


def test_incident_candidate_requires_at_least_one_service_and_evidence() -> None:
    with pytest.raises(ValidationError):
        IncidentCandidate(
            id=INCIDENT_ID,
            workspace_id=WORKSPACE_ID,
            detected_at="2026-08-05T10:05:00Z",
            window_start="2026-08-05T10:00:00Z",
            window_end="2026-08-05T10:05:00Z",
            affected_services=[],
            evidence=[],
            suggested_severity="low",
        )


def test_evidence_item_rejects_invalid_source_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(**{**_evidence("2026-08-05T10:02:00Z"), "source_type": "carrier_pigeon"})


def test_evidence_item_rejects_relevance_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(**{**_evidence("2026-08-05T10:02:00Z"), "relevance_score": 1.5})
