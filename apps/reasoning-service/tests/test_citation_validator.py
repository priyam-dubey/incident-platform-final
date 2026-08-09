import uuid
from datetime import datetime, timezone

from app.citation_validator import validate_citations
from app.structured_output import HypothesisDraft, HypothesisSetDraft
from incident_schemas import EvidenceItem, IncidentCandidate, ServiceAnomaly

WORKSPACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SERVICE_ID = uuid.uuid4()
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _evidence(id_: uuid.UUID, service_name: str = "checkout-api") -> EvidenceItem:
    return EvidenceItem(
        id=id_,
        source_type="log",
        source_ref=f"log:{id_}",
        service_name=service_name,
        snippet="connection pool exhausted",
        relevance_score=0.9,
        occurred_at=T0,
    )


def _candidate(evidence: list[EvidenceItem]) -> IncidentCandidate:
    return IncidentCandidate(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        detected_at=T0,
        window_start=T0,
        window_end=T0,
        affected_services=[
            ServiceAnomaly(
                service_id=SERVICE_ID,
                service_name="checkout-api",
                anomaly_score=5.0,
                metric_name="error_rate",
                observed_value=0.5,
                baseline_mean=0.01,
                baseline_stddev=0.02,
            )
        ],
        evidence=evidence,
        suggested_severity="high",
    )


def test_accepts_hypothesis_citing_real_evidence() -> None:
    evidence_id = uuid.uuid4()
    candidate = _candidate([_evidence(evidence_id)])
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Connection pool exhaustion caused cascading timeouts.",
                confidence=0.8,
                cited_evidence_ids=[evidence_id],
            )
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    assert result.has_any_valid_hypothesis
    assert len(result.accepted) == 1
    assert len(result.rejected) == 0


def test_rejects_hypothesis_citing_fabricated_evidence_id() -> None:
    real_id = uuid.uuid4()
    fabricated_id = uuid.uuid4()
    candidate = _candidate([_evidence(real_id)])
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Root cause is a fabricated database deadlock event.",
                confidence=0.9,
                cited_evidence_ids=[fabricated_id],  # never existed in the candidate's evidence
            )
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    assert not result.has_any_valid_hypothesis
    assert len(result.rejected) == 1
    assert "not present in the incident candidate" in result.rejected[0].reason


def test_partial_hallucination_rejects_only_the_offending_hypothesis() -> None:
    real_id = uuid.uuid4()
    fabricated_id = uuid.uuid4()
    candidate = _candidate([_evidence(real_id)])
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Valid hypothesis grounded in real evidence.",
                confidence=0.7,
                cited_evidence_ids=[real_id],
            ),
            HypothesisDraft(
                hypothesis="Invalid hypothesis citing evidence that does not exist.",
                confidence=0.95,
                cited_evidence_ids=[fabricated_id],
            ),
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.accepted[0].hypothesis == "Valid hypothesis grounded in real evidence."


def test_accepted_hypotheses_are_ranked_by_confidence_descending() -> None:
    id_a, id_b, id_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    candidate = _candidate([_evidence(id_a), _evidence(id_b), _evidence(id_c)])
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(hypothesis="Low confidence hypothesis text here.", confidence=0.3, cited_evidence_ids=[id_a]),
            HypothesisDraft(hypothesis="High confidence hypothesis text here.", confidence=0.9, cited_evidence_ids=[id_b]),
            HypothesisDraft(hypothesis="Medium confidence hypothesis text.", confidence=0.6, cited_evidence_ids=[id_c]),
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    confidences = [h.confidence for h in result.accepted]
    assert confidences == sorted(confidences, reverse=True)


def test_detects_cross_service_citations_without_rejecting_them() -> None:
    checkout_evidence = uuid.uuid4()
    payments_evidence = uuid.uuid4()
    candidate = _candidate(
        [_evidence(checkout_evidence, "checkout-api"), _evidence(payments_evidence, "payments-api")]
    )
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Payments-api slowdown propagated into checkout-api timeouts.",
                confidence=0.75,
                cited_evidence_ids=[checkout_evidence, payments_evidence],
            )
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    assert result.has_any_valid_hypothesis
    assert result.accepted[0].cross_service_citation_count == 1


def test_multiple_fabricated_ids_in_one_hypothesis_are_all_reported() -> None:
    real_id = uuid.uuid4()
    fabricated_1, fabricated_2 = uuid.uuid4(), uuid.uuid4()
    candidate = _candidate([_evidence(real_id)])
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Hypothesis citing two fabricated evidence entries.",
                confidence=0.5,
                cited_evidence_ids=[fabricated_1, fabricated_2],
            )
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)

    assert len(result.rejected) == 1
    assert str(fabricated_1) in result.rejected[0].reason
    assert str(fabricated_2) in result.rejected[0].reason


def test_empty_evidence_set_rejects_every_hypothesis() -> None:
    candidate = _candidate([_evidence(uuid.uuid4())])  # schema requires >=1, use a real unrelated id
    unrelated_id = uuid.uuid4()
    draft = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Hypothesis citing an id from a different incident entirely.",
                confidence=0.5,
                cited_evidence_ids=[unrelated_id],
            )
        ],
        evidence_sufficient=True,
    )

    result = validate_citations(draft, candidate)
    assert not result.has_any_valid_hypothesis
