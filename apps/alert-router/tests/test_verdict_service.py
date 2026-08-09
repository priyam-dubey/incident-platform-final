import uuid
from datetime import datetime, timezone

import pytest

from app.repository import HypothesisRecord, IncidentRecord
from app.verdict_service import HypothesisNotFoundError, apply_verdict

WORKSPACE_ID = uuid.uuid4()
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _seed_incident(repo, incident_id, status="pending_review"):
    repo.incidents[incident_id] = IncidentRecord(
        id=incident_id, workspace_id=WORKSPACE_ID, status=status,
        severity="high", started_at=T0, resolved_at=None,
    )


def _seed_hypothesis(repo, hyp_id, incident_id, rank=1):
    repo.hypotheses[hyp_id] = HypothesisRecord(
        id=hyp_id, incident_id=incident_id, rank=rank,
        hypothesis="Some root cause hypothesis.", confidence=0.8,
        cited_evidence_ids=[], human_verdict=None, reviewed_by=None,
    )


async def test_accepting_a_hypothesis_publishes_the_incident(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_id, incident_id)

    outcome = await apply_verdict(fake_repo, hyp_id, "accepted", None, "alice@company.com")

    assert outcome.hypothesis.human_verdict == "accepted"
    assert outcome.incident_status == "published"
    assert fake_repo.incidents[incident_id].status == "published"


async def test_editing_a_hypothesis_also_publishes_the_incident(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_id, incident_id)

    outcome = await apply_verdict(fake_repo, hyp_id, "edited", "corrected wording", "alice@company.com")

    assert outcome.incident_status == "published"


async def test_rejecting_the_only_hypothesis_dismisses_the_incident(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_id, incident_id)

    outcome = await apply_verdict(fake_repo, hyp_id, "rejected", "not the cause", "alice@company.com")

    assert outcome.incident_status == "dismissed"
    assert fake_repo.incidents[incident_id].status == "dismissed"


async def test_rejecting_one_of_several_hypotheses_leaves_incident_pending(fake_repo) -> None:
    incident_id = uuid.uuid4()
    hyp_1, hyp_2 = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_1, incident_id, rank=1)
    _seed_hypothesis(fake_repo, hyp_2, incident_id, rank=2)

    outcome = await apply_verdict(fake_repo, hyp_1, "rejected", None, "alice@company.com")

    # hyp_2 is still unreviewed, so the incident must not be dismissed yet.
    assert outcome.incident_status == "pending_review"
    assert fake_repo.incidents[incident_id].status == "pending_review"


async def test_rejecting_all_hypotheses_eventually_dismisses(fake_repo) -> None:
    incident_id = uuid.uuid4()
    hyp_1, hyp_2 = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_1, incident_id, rank=1)
    _seed_hypothesis(fake_repo, hyp_2, incident_id, rank=2)

    await apply_verdict(fake_repo, hyp_1, "rejected", None, "alice@company.com")
    outcome = await apply_verdict(fake_repo, hyp_2, "rejected", None, "bob@company.com")

    assert outcome.incident_status == "dismissed"


async def test_every_verdict_writes_an_eval_example(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_id, incident_id)

    await apply_verdict(fake_repo, hyp_id, "accepted", None, "alice@company.com")

    assert fake_repo.eval_examples == [(hyp_id, "accepted")]


async def test_verdict_on_unknown_hypothesis_raises(fake_repo) -> None:
    with pytest.raises(HypothesisNotFoundError):
        await apply_verdict(fake_repo, uuid.uuid4(), "accepted", None, "alice@company.com")


async def test_invalid_verdict_string_raises_value_error(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    _seed_incident(fake_repo, incident_id)
    _seed_hypothesis(fake_repo, hyp_id, incident_id)

    with pytest.raises(ValueError):
        await apply_verdict(fake_repo, hyp_id, "maybe", None, "alice@company.com")
