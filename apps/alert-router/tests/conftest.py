from __future__ import annotations

import uuid

import pytest

from app.repository import EvidenceRecord, HypothesisRecord, IncidentDetail, IncidentRecord


class FakeIncidentRepository:
    """
    In-memory fake matching the IncidentRepository protocol. Seeded directly
    via self.incidents / self.hypotheses in tests rather than through a
    constructor, so each test can set up exactly the scenario it needs.
    """

    def __init__(self) -> None:
        self.incidents: dict[uuid.UUID, IncidentRecord] = {}
        self.evidence: dict[uuid.UUID, list[EvidenceRecord]] = {}
        self.hypotheses: dict[uuid.UUID, HypothesisRecord] = {}  # keyed by hypothesis id
        self.eval_examples: list[tuple[uuid.UUID, str]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def list_incidents(self, workspace_id, status, limit):
        results = [i for i in self.incidents.values() if i.workspace_id == workspace_id]
        if status:
            results = [i for i in results if i.status == status]
        return sorted(results, key=lambda i: i.started_at, reverse=True)[:limit]

    async def get_incident_detail(self, incident_id):
        incident = self.incidents.get(incident_id)
        if incident is None:
            return None
        hyps = [h for h in self.hypotheses.values() if h.incident_id == incident_id]
        return IncidentDetail(
            incident=incident,
            evidence=self.evidence.get(incident_id, []),
            hypotheses=sorted(hyps, key=lambda h: h.rank),
        )

    async def record_verdict(self, hypothesis_id, verdict, notes, reviewed_by):
        existing = self.hypotheses.get(hypothesis_id)
        if existing is None:
            return None
        updated = HypothesisRecord(
            id=existing.id,
            incident_id=existing.incident_id,
            rank=existing.rank,
            hypothesis=existing.hypothesis,
            confidence=existing.confidence,
            cited_evidence_ids=existing.cited_evidence_ids,
            human_verdict=verdict,
            reviewed_by=reviewed_by,
        )
        self.hypotheses[hypothesis_id] = updated
        return updated

    async def mark_incident_status(self, incident_id, status):
        incident = self.incidents[incident_id]
        self.incidents[incident_id] = IncidentRecord(
            id=incident.id, workspace_id=incident.workspace_id, status=status,
            severity=incident.severity, started_at=incident.started_at, resolved_at=incident.resolved_at,
        )

    async def record_eval_example(self, hypothesis_id, label):
        self.eval_examples.append((hypothesis_id, label))


@pytest.fixture
def fake_repo() -> FakeIncidentRepository:
    return FakeIncidentRepository()
