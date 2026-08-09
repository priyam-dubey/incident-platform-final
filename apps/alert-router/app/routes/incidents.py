"""
The HTTP surface the dashboard (Phase 6) calls: list incidents, fetch one
with its full evidence + hypotheses, and submit a human verdict on a
hypothesis. This is deliberately the *only* way hypothesis review state
changes - there is no direct DB write path from the dashboard, everything
goes through apply_verdict() so the eval_examples/incident-status side
effects documented in verdict_service.py always happen together.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key, require_reviewer_identity
from app.metrics import VERDICTS_SUBMITTED_TOTAL
from app.verdict_service import HypothesisNotFoundError, apply_verdict

router = APIRouter(prefix="/v1", tags=["incidents"], dependencies=[Depends(require_api_key)])


class EvidenceOut(BaseModel):
    id: uuid.UUID
    source_type: str
    source_ref: str
    snippet: str
    relevance_score: float
    occurred_at: str


class HypothesisOut(BaseModel):
    id: uuid.UUID
    rank: int
    hypothesis: str
    confidence: float
    cited_evidence_ids: list[uuid.UUID]
    human_verdict: str | None
    reviewed_by: str | None


class IncidentSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    severity: str
    started_at: str
    resolved_at: str | None


class IncidentDetailOut(BaseModel):
    incident: IncidentSummaryOut
    evidence: list[EvidenceOut]
    hypotheses: list[HypothesisOut]


class VerdictRequest(BaseModel):
    verdict: str = Field(pattern="^(accepted|rejected|edited)$")
    notes: str | None = Field(default=None, max_length=2000)


class VerdictResponse(BaseModel):
    hypothesis: HypothesisOut
    incident_status: str


def _get_repo(request: Request):
    return request.app.state.repository


@router.get("/incidents", response_model=list[IncidentSummaryOut])
async def list_incidents(
    request: Request,
    workspace_id: uuid.UUID,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[IncidentSummaryOut]:
    repo = _get_repo(request)
    incidents = await repo.list_incidents(workspace_id, status_filter, min(limit, 200))
    return [
        IncidentSummaryOut(
            id=i.id, status=i.status, severity=i.severity,
            started_at=i.started_at.isoformat(),
            resolved_at=i.resolved_at.isoformat() if i.resolved_at else None,
        )
        for i in incidents
    ]


@router.get("/incidents/{incident_id}", response_model=IncidentDetailOut)
async def get_incident(request: Request, incident_id: uuid.UUID) -> IncidentDetailOut:
    repo = _get_repo(request)
    detail = await repo.get_incident_detail(incident_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    return IncidentDetailOut(
        incident=IncidentSummaryOut(
            id=detail.incident.id, status=detail.incident.status, severity=detail.incident.severity,
            started_at=detail.incident.started_at.isoformat(),
            resolved_at=detail.incident.resolved_at.isoformat() if detail.incident.resolved_at else None,
        ),
        evidence=[
            EvidenceOut(
                id=e.id, source_type=e.source_type, source_ref=e.source_ref, snippet=e.snippet,
                relevance_score=e.relevance_score, occurred_at=e.occurred_at.isoformat(),
            )
            for e in detail.evidence
        ],
        hypotheses=[
            HypothesisOut(
                id=h.id, rank=h.rank, hypothesis=h.hypothesis, confidence=h.confidence,
                cited_evidence_ids=h.cited_evidence_ids, human_verdict=h.human_verdict,
                reviewed_by=h.reviewed_by,
            )
            for h in detail.hypotheses
        ],
    )


@router.post("/hypotheses/{hypothesis_id}/verdict", response_model=VerdictResponse)
async def submit_verdict(
    request: Request,
    hypothesis_id: uuid.UUID,
    body: VerdictRequest,
    reviewer: str = Depends(require_reviewer_identity),
) -> VerdictResponse:
    repo = _get_repo(request)
    try:
        outcome = await apply_verdict(repo, hypothesis_id, body.verdict, body.notes, reviewer)
    except HypothesisNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found")

    VERDICTS_SUBMITTED_TOTAL.labels(body.verdict).inc()

    return VerdictResponse(
        hypothesis=HypothesisOut(
            id=outcome.hypothesis.id, rank=outcome.hypothesis.rank,
            hypothesis=outcome.hypothesis.hypothesis, confidence=outcome.hypothesis.confidence,
            cited_evidence_ids=outcome.hypothesis.cited_evidence_ids,
            human_verdict=outcome.hypothesis.human_verdict, reviewed_by=outcome.hypothesis.reviewed_by,
        ),
        incident_status=outcome.incident_status,
    )
