"""Workspace-scoped incident, deployment and notification APIs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from incident_llm import LLMClient
from incident_llm.errors import LLMError

from app import incident_service, notifier, rca
from app.config import Settings, get_settings
from app.deps import WorkspaceContext, get_repo, workspace_access
from app.repository import Repository
from app.schemas import DeploymentCreate, HypothesisReview, IncidentTransition, NoteCreate
from app.security import constant_time_equal, parse_ingestion_key, sha256_hex

logger = logging.getLogger("incidents")
router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["incidents"])
ingest_router = APIRouter(prefix="/v1", tags=["deployments"])
STATUSES = {"candidate", "analyzing", "pending_review", "published", "dismissed", "resolved"}


def _iso(v):
    return v.isoformat() if v else None


def _incident(i: dict) -> dict:
    return {"id": str(i["id"]), "title": i["title"], "status": i["status"], "severity": i["severity"], "detector": i["detector"],
            "application_id": str(i["application_id"]) if i["application_id"] else None, "application_name": i.get("application_name"),
            "started_at": _iso(i["started_at"]), "resolved_at": _iso(i["resolved_at"]), "details": i["details"],
            "synthetic": i["is_synthetic"], "updated_at": _iso(i["updated_at"])}


def _deployment(d: dict) -> dict:
    return {"id": str(d["id"]), "application_id": str(d["application_id"]), "application_name": d.get("application_name"),
            "version": d["version"], "commit_sha": d["commit_sha"], "branch": d["branch"], "repository": d["repository_full_name"],
            "environment": d["environment"], "deployed_by": d["deployed_by"], "source": d["source"], "deployed_at": _iso(d["deployed_at"]),
            "metadata": d["metadata"]}


def _hyp(h: dict) -> dict:
    return {"id": str(h["id"]), "rank": h["rank"], "hypothesis": h["hypothesis"], "edited_text": h["edited_text"],
            "confidence": float(h["confidence"]), "cited_evidence_ids": [str(x) for x in h["cited_evidence_ids"]],
            "human_verdict": h["human_verdict"], "verdict_notes": h["verdict_notes"], "reviewed_by": h["reviewed_by"],
            "reviewed_at": _iso(h["reviewed_at"]), "model": h["model_name"], "ai_generated": True,
            "kind": "hypothesis_not_proof"}


# ---------------------------------------------------------------- deployments
@router.get("/deployments")
def list_deployments(application_id: uuid.UUID | None = None, limit: int = Query(50, ge=1, le=200),
                     ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    return [_deployment(d) for d in repo.list_deployments(ctx.workspace_id, application_id, limit)]


@router.post("/applications/{application_id}/deployments", status_code=201)
def register_deployment_user(application_id: uuid.UUID, body: DeploymentCreate,
                             ctx: WorkspaceContext = Depends(workspace_access("developer")), repo: Repository = Depends(get_repo)):
    app = repo.get_application(ctx.workspace_id, application_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    d = repo.create_deployment(ctx.workspace_id, application_id, body.environment or app["environment"], body.version, body.commit_sha,
                               body.branch, body.repository, body.deployed_by or ctx.user["email"], "manual", body.deployed_at, body.metadata)
    repo.audit(ctx.workspace_id, ctx.user["id"], "deployment.registered", "deployment", str(d["id"]), {"commit_sha": body.commit_sha})
    return _deployment(d)


@ingest_router.post("/deployments", status_code=201)
def register_deployment_key(body: DeploymentCreate, request: Request, repo: Repository = Depends(get_repo)):
    """SDK/CI endpoint: authenticated with the application's ingestion key (X-Ingestion-Key). Workspace and
    application come from the key, never from the payload."""
    key = request.headers.get("x-ingestion-key", "")
    prefix = parse_ingestion_key(key) if key else None
    row = repo.lookup_ingestion_key(prefix) if prefix else None
    if row is None or not constant_time_equal(sha256_hex(key), row["key_hash"]):
        raise HTTPException(401, "Invalid ingestion key")
    d = repo.create_deployment(row["workspace_id"], row["application_id"], row["environment"], body.version, body.commit_sha, body.branch,
                               body.repository, body.deployed_by, "sdk", body.deployed_at, body.metadata)
    repo.audit(row["workspace_id"], None, "deployment.registered", "deployment", str(d["id"]), {"via": "ingestion_key", "commit_sha": body.commit_sha})
    return _deployment(d)


# ------------------------------------------------------------------ incidents
@router.get("/incidents")
def list_incidents(status_: str | None = Query(None, alias="status"), application_id: uuid.UUID | None = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    if status_ and status_ not in STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
    return [_incident(i) for i in repo.list_incidents(ctx.workspace_id, status_, application_id, limit, offset)]


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo),
                 settings: Settings = Depends(get_settings)):
    inc = repo.get_incident(ctx.workspace_id, incident_id)
    if inc is None:
        raise HTTPException(404, "Incident not found")
    deployments = []
    if inc["application_id"]:
        deployments = repo.deployments_between(ctx.workspace_id, inc["application_id"],
                                               inc["started_at"] - timedelta(hours=2), inc["started_at"] + timedelta(minutes=10))
    return {"incident": _incident(inc),
            "evidence": [{"id": str(e["id"]), "source_type": e["source_type"], "source_ref": e["source_ref"], "snippet": e["snippet"],
                          "relevance_score": float(e["relevance_score"]), "occurred_at": _iso(e["occurred_at"])} for e in repo.list_evidence(incident_id)],
            "hypotheses": [_hyp(h) for h in repo.list_hypotheses(incident_id)],
            "notes": [{"id": str(n["id"]), "body": n["body"], "author": n["author_email"], "created_at": _iso(n["created_at"])}
                      for n in repo.list_notes(ctx.workspace_id, incident_id)],
            "related_deployments": [_deployment(d) for d in deployments],
            "notifications": [{"channel": n["channel"], "status": n["status"], "at": _iso(n["created_at"])} for n in repo.list_notifications(ctx.workspace_id, incident_id)],
            "ai": {**LLMClient().status(), "disclaimer": "Hypotheses are AI-generated from the listed evidence and are not proof of cause."}}


@router.post("/incidents/{incident_id}/status")
def transition(incident_id: uuid.UUID, body: IncidentTransition, ctx: WorkspaceContext = Depends(workspace_access("developer")),
               repo: Repository = Depends(get_repo)):
    inc = repo.transition_incident(ctx.workspace_id, incident_id, body.status, ctx.user["id"])
    if inc is None:
        raise HTTPException(404, "Incident not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], f"incident.{body.status}", "incident", str(incident_id))
    return {"id": str(incident_id), "status": inc["status"]}


@router.post("/incidents/{incident_id}/notes", status_code=201)
def add_note(incident_id: uuid.UUID, body: NoteCreate, ctx: WorkspaceContext = Depends(workspace_access("developer")),
             repo: Repository = Depends(get_repo)):
    n = repo.add_note(ctx.workspace_id, incident_id, ctx.user["id"], body.body)
    if n is None:
        raise HTTPException(404, "Incident not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], "incident.note_added", "incident", str(incident_id))
    return {"id": str(n["id"]), "body": n["body"], "author": ctx.user["email"], "created_at": _iso(n["created_at"])}


@router.post("/incidents/{incident_id}/hypotheses/{hypothesis_id}/review")
def review(incident_id: uuid.UUID, hypothesis_id: uuid.UUID, body: HypothesisReview,
           ctx: WorkspaceContext = Depends(workspace_access("developer")), repo: Repository = Depends(get_repo)):
    h = repo.review_hypothesis(ctx.workspace_id, incident_id, hypothesis_id, body.verdict, body.notes, body.edited_text, ctx.user["email"])
    if h is None:
        raise HTTPException(404, "Hypothesis not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], f"hypothesis.{body.verdict}", "hypothesis", str(hypothesis_id), {"incident_id": str(incident_id)})
    return _hyp(h)


@router.post("/incidents/{incident_id}/analyze")
def analyze(incident_id: uuid.UUID, request: Request, ctx: WorkspaceContext = Depends(workspace_access("developer")),
            repo: Repository = Depends(get_repo)):
    """(Re)run the evidence-grounded RCA for this incident via the central LLM client."""
    inc = repo.get_incident(ctx.workspace_id, incident_id)
    if inc is None:
        raise HTTPException(404, "Incident not found")
    result = run_rca(repo, inc, getattr(request.app.state, "llm", None))
    repo.audit(ctx.workspace_id, ctx.user["id"], "incident.analyzed", "incident", str(incident_id), {"result": result["state"]})
    if result["state"] in ("not_configured", "invalid_config"):
        raise HTTPException(503, detail={"code": f"llm_{result['state']}", "message": result["detail"]})
    return result


def run_rca(repo: Repository, inc: dict, llm=None) -> dict:
    llm = llm or LLMClient()
    evidence = repo.list_evidence(inc["id"])
    if not evidence:
        return {"state": "no_evidence", "detail": "No evidence is available for this incident.", "hypotheses": 0}
    st = llm.status()
    if st["state"] != "configured":
        repo.set_incident_details(inc["id"], {"rca": {"state": st["state"]}})
        return {"state": st["state"], "detail": st["detail"], "hypotheses": 0}
    try:
        hyps = asyncio.run(rca.generate(llm, inc, evidence))
    except LLMError as exc:
        repo.set_incident_details(inc["id"], {"rca": {"state": "failed", "error_code": exc.code}})
        return {"state": "failed", "detail": exc.code, "hypotheses": 0}
    repo.save_hypotheses(inc["id"], rca.to_rows(hyps), rca.PROMPT_VERSION, st["model"])
    repo.set_incident_details(inc["id"], {"rca": {"state": "completed", "hypotheses": len(hyps)}})
    return {"state": "completed", "detail": None, "hypotheses": len(hyps)}


@router.post("/applications/{application_id}/detect")
def detect_now(application_id: uuid.UUID, request: Request, ctx: WorkspaceContext = Depends(workspace_access("developer")),
               repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    """Run detection immediately for one application (also what the background loop does)."""
    app = repo.get_application(ctx.workspace_id, application_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    executor = getattr(request.app.state, "telemetry", None)
    if executor is None:
        raise HTTPException(503, detail={"code": "telemetry_store_not_configured", "message": "Set CLICKHOUSE_URL."})
    found = process_application(repo, executor, app, settings, getattr(request.app.state, "llm", None))
    return {"incidents": [_incident(i) for i in found]}


def process_application(repo, executor, app: dict, settings: Settings, llm=None, transport=None) -> list[dict]:
    out = []
    for inc, created, _scope, _det in incident_service.detect_application(repo, executor, app):
        if created:
            repo.audit(app["workspace_id"], None, "incident.detected", "incident", str(inc["id"]), {"detector": inc["detector"]})
            if settings.rca_enabled:
                run_rca(repo, inc, llm)
            link = f"{settings.dashboard_url.rstrip('/')}/incidents/{inc['id']}"
            for ch, st, err in notifier.notify(settings, {**inc, "application_name": app["name"]}, link, transport):
                repo.record_notification(app["workspace_id"], inc["id"], ch, st, err)
        out.append(repo.get_incident(app["workspace_id"], inc["id"]))
    return out


@router.get("/integrations/status")
def integrations_status(request: Request, ctx: WorkspaceContext = Depends(workspace_access("viewer")), settings: Settings = Depends(get_settings)):
    """Honest configuration state for each external integration (no secret values)."""
    from app import github_app
    return {"llm": LLMClient().status(), "notifications": notifier.channel_status(settings),
            "github_app": github_app.status(settings),
            "telemetry_store": "configured" if getattr(request.app.state, "telemetry", None) is not None else "not_configured"}
