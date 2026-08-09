import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import HypothesisRecord, IncidentRecord

WORKSPACE_ID = uuid.uuid4()
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)
VALID_KEY = "dev-local-dashboard-key"


def _client(fake_repo) -> TestClient:
    app = create_app(repository_factory=lambda settings: fake_repo, enable_escalation_consumer=False)
    return TestClient(app)


def test_healthz_requires_no_auth(fake_repo) -> None:
    with _client(fake_repo) as client:
        response = client.get("/healthz")
    assert response.status_code == 200


def test_list_incidents_requires_api_key(fake_repo) -> None:
    with _client(fake_repo) as client:
        response = client.get(f"/v1/incidents?workspace_id={WORKSPACE_ID}")
    assert response.status_code == 401


def test_list_incidents_returns_seeded_data(fake_repo) -> None:
    incident_id = uuid.uuid4()
    fake_repo.incidents[incident_id] = IncidentRecord(
        id=incident_id, workspace_id=WORKSPACE_ID, status="pending_review",
        severity="high", started_at=T0, resolved_at=None,
    )

    with _client(fake_repo) as client:
        response = client.get(
            f"/v1/incidents?workspace_id={WORKSPACE_ID}", headers={"X-API-Key": VALID_KEY}
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(incident_id)


def test_get_incident_detail_includes_hypotheses_and_evidence(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    fake_repo.incidents[incident_id] = IncidentRecord(
        id=incident_id, workspace_id=WORKSPACE_ID, status="pending_review",
        severity="critical", started_at=T0, resolved_at=None,
    )
    fake_repo.hypotheses[hyp_id] = HypothesisRecord(
        id=hyp_id, incident_id=incident_id, rank=1, hypothesis="Root cause text",
        confidence=0.9, cited_evidence_ids=[], human_verdict=None, reviewed_by=None,
    )

    with _client(fake_repo) as client:
        response = client.get(f"/v1/incidents/{incident_id}", headers={"X-API-Key": VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["incident"]["id"] == str(incident_id)
    assert len(body["hypotheses"]) == 1
    assert body["hypotheses"][0]["hypothesis"] == "Root cause text"


def test_get_unknown_incident_returns_404(fake_repo) -> None:
    with _client(fake_repo) as client:
        response = client.get(f"/v1/incidents/{uuid.uuid4()}", headers={"X-API-Key": VALID_KEY})
    assert response.status_code == 404


def test_submit_verdict_requires_reviewer_header(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    fake_repo.incidents[incident_id] = IncidentRecord(
        id=incident_id, workspace_id=WORKSPACE_ID, status="pending_review",
        severity="high", started_at=T0, resolved_at=None,
    )
    fake_repo.hypotheses[hyp_id] = HypothesisRecord(
        id=hyp_id, incident_id=incident_id, rank=1, hypothesis="Root cause text",
        confidence=0.9, cited_evidence_ids=[], human_verdict=None, reviewed_by=None,
    )

    with _client(fake_repo) as client:
        response = client.post(
            f"/v1/hypotheses/{hyp_id}/verdict",
            json={"verdict": "accepted"},
            headers={"X-API-Key": VALID_KEY},  # no X-Reviewer-Email
        )

    assert response.status_code == 400


def test_submit_verdict_accepted_publishes_incident(fake_repo) -> None:
    incident_id, hyp_id = uuid.uuid4(), uuid.uuid4()
    fake_repo.incidents[incident_id] = IncidentRecord(
        id=incident_id, workspace_id=WORKSPACE_ID, status="pending_review",
        severity="high", started_at=T0, resolved_at=None,
    )
    fake_repo.hypotheses[hyp_id] = HypothesisRecord(
        id=hyp_id, incident_id=incident_id, rank=1, hypothesis="Root cause text",
        confidence=0.9, cited_evidence_ids=[], human_verdict=None, reviewed_by=None,
    )

    with _client(fake_repo) as client:
        response = client.post(
            f"/v1/hypotheses/{hyp_id}/verdict",
            json={"verdict": "accepted", "notes": "confirmed via runbook"},
            headers={"X-API-Key": VALID_KEY, "X-Reviewer-Email": "alice@company.com"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["incident_status"] == "published"
    assert body["hypothesis"]["human_verdict"] == "accepted"
    assert body["hypothesis"]["reviewed_by"] == "alice@company.com"


def test_submit_verdict_on_unknown_hypothesis_returns_404(fake_repo) -> None:
    with _client(fake_repo) as client:
        response = client.post(
            f"/v1/hypotheses/{uuid.uuid4()}/verdict",
            json={"verdict": "accepted"},
            headers={"X-API-Key": VALID_KEY, "X-Reviewer-Email": "alice@company.com"},
        )
    assert response.status_code == 404


def test_submit_verdict_rejects_invalid_verdict_value(fake_repo) -> None:
    with _client(fake_repo) as client:
        response = client.post(
            f"/v1/hypotheses/{uuid.uuid4()}/verdict",
            json={"verdict": "maybe"},
            headers={"X-API-Key": VALID_KEY, "X-Reviewer-Email": "alice@company.com"},
        )
    assert response.status_code == 422  # fails Pydantic pattern validation before reaching the service


def test_metrics_endpoint_exposes_prometheus_format(fake_repo) -> None:
    with _client(fake_repo) as client:
        client.get("/healthz")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
