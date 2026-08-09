import uuid
from datetime import datetime, timezone

from app.reasoning_graph import ReasoningPipeline
from app.structured_output import HypothesisDraft, HypothesisSetDraft
from incident_schemas import EvidenceItem, IncidentCandidate, ServiceAnomaly

WORKSPACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _candidate(evidence_id: uuid.UUID) -> IncidentCandidate:
    return IncidentCandidate(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        detected_at=T0,
        window_start=T0,
        window_end=T0,
        affected_services=[
            ServiceAnomaly(
                service_id=uuid.uuid4(),
                service_name="checkout-api",
                anomaly_score=5.0,
                metric_name="error_rate",
                observed_value=0.5,
                baseline_mean=0.01,
                baseline_stddev=0.02,
            )
        ],
        evidence=[
            EvidenceItem(
                id=evidence_id,
                source_type="log",
                source_ref=f"log:{evidence_id}",
                service_name="checkout-api",
                snippet="connection pool exhausted",
                relevance_score=0.9,
                occurred_at=T0,
            )
        ],
        suggested_severity="high",
    )


async def test_accepts_immediately_when_first_attempt_is_clean(make_fake_llm_client) -> None:
    evidence_id = uuid.uuid4()
    candidate = _candidate(evidence_id)

    clean_response = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Connection pool exhaustion caused the error spike.",
                confidence=0.85,
                cited_evidence_ids=[evidence_id],
            )
        ],
        evidence_sufficient=True,
    )
    fake_client = make_fake_llm_client([clean_response])
    pipeline = ReasoningPipeline(llm_client=fake_client, max_attempts=2)

    result = await pipeline.run(candidate, model="gemini-2.5-flash")

    assert result.has_any_valid_hypothesis
    assert fake_client.call_count == 1  # no retry needed


async def test_retries_once_after_hallucinated_citation_then_succeeds(make_fake_llm_client) -> None:
    evidence_id = uuid.uuid4()
    fabricated_id = uuid.uuid4()
    candidate = _candidate(evidence_id)

    hallucinated_response = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="A hallucinated root cause citing evidence that was never provided.",
                confidence=0.9,
                cited_evidence_ids=[fabricated_id],
            )
        ],
        evidence_sufficient=True,
    )
    corrected_response = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Connection pool exhaustion, correctly grounded this time.",
                confidence=0.8,
                cited_evidence_ids=[evidence_id],
            )
        ],
        evidence_sufficient=True,
    )
    fake_client = make_fake_llm_client([hallucinated_response, corrected_response])
    pipeline = ReasoningPipeline(llm_client=fake_client, max_attempts=2)

    result = await pipeline.run(candidate, model="gemini-2.5-flash")

    assert result.has_any_valid_hypothesis
    assert fake_client.call_count == 2
    # The retry prompt must actually differ (contains the correction notice) -
    # otherwise the model has no reason to behave differently on attempt 2.
    first_system_prompt = fake_client.received_prompts[0][0]
    second_system_prompt = fake_client.received_prompts[1][0]
    assert first_system_prompt != second_system_prompt
    assert "IMPORTANT" in second_system_prompt


async def test_gives_up_after_max_attempts_with_empty_accepted_list(make_fake_llm_client) -> None:
    evidence_id = uuid.uuid4()
    fabricated_id_1, fabricated_id_2 = uuid.uuid4(), uuid.uuid4()
    candidate = _candidate(evidence_id)

    always_hallucinates = [
        HypothesisSetDraft(
            hypotheses=[
                HypothesisDraft(
                    hypothesis=f"Hallucinated hypothesis attempt with fabricated citation {i}.",
                    confidence=0.9,
                    cited_evidence_ids=[fid],
                )
            ],
            evidence_sufficient=True,
        )
        for i, fid in enumerate([fabricated_id_1, fabricated_id_2])
    ]
    fake_client = make_fake_llm_client(always_hallucinates)
    pipeline = ReasoningPipeline(llm_client=fake_client, max_attempts=2)

    result = await pipeline.run(candidate, model="gemini-2.5-flash")

    assert not result.has_any_valid_hypothesis
    assert len(result.rejected) == 1  # only the final attempt's rejection is returned
    assert fake_client.call_count == 2  # exactly max_attempts calls, not more


async def test_max_attempts_of_one_means_no_retry_at_all(make_fake_llm_client) -> None:
    evidence_id = uuid.uuid4()
    fabricated_id = uuid.uuid4()
    candidate = _candidate(evidence_id)

    hallucinated = HypothesisSetDraft(
        hypotheses=[
            HypothesisDraft(
                hypothesis="Hallucinated hypothesis with no valid citation at all.",
                confidence=0.9,
                cited_evidence_ids=[fabricated_id],
            )
        ],
        evidence_sufficient=True,
    )
    fake_client = make_fake_llm_client([hallucinated])
    pipeline = ReasoningPipeline(llm_client=fake_client, max_attempts=1)

    result = await pipeline.run(candidate, model="gemini-2.5-flash")

    assert not result.has_any_valid_hypothesis
    assert fake_client.call_count == 1


def test_prompt_version_is_exposed_for_persistence() -> None:
    pipeline = ReasoningPipeline(llm_client=object())  # not called in this test
    assert pipeline.prompt_version == "root_cause_v1"
