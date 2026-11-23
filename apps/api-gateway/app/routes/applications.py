from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import Settings, get_settings
from app.deps import WorkspaceContext, get_repo, workspace_access
from app.repository import DuplicateError, Repository
from app.schemas import ApplicationCreate
from app.security import generate_ingestion_key

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/applications", tags=["applications"])
STALE_AFTER = timedelta(minutes=10)


def _status(app: dict) -> str:
    last = app["last_telemetry_at"]
    if last is None:
        return "waiting_for_telemetry"
    return "connected" if datetime.now(timezone.utc) - last < STALE_AFTER else "stale"


def _out(app: dict) -> dict:
    last = app["last_telemetry_at"]
    return {
        "id": str(app["id"]), "name": app["name"], "environment": app["environment"], "framework": app["framework"],
        "backend_url": app["backend_url"], "is_synthetic": app["is_synthetic"], "connection_status": _status(app),
        "last_telemetry_at": last.isoformat() if last else None, "active_key_prefix": app.get("active_key_prefix"),
        "created_at": app["created_at"].isoformat(),
    }


def _onboarding(app: dict, settings: Settings) -> dict:
    return {
        "ingestion_endpoint": settings.public_ingestion_url.rstrip("/") + "/v1/telemetry",
        "key_header": "X-Ingestion-Key",
        "env": {"INCIDENT_PLATFORM_ENDPOINT": settings.public_ingestion_url.rstrip("/"),
                "INCIDENT_PLATFORM_KEY": "<the key shown once at creation/rotation>",
                "INCIDENT_PLATFORM_APP": app["name"], "INCIDENT_PLATFORM_ENV": app["environment"]},
        "note": "Ingestion keys are shown only once. Rotate the key if it was lost.",
    }


@router.get("")
def list_applications(ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    return [_out(a) for a in repo.list_applications(ctx.workspace_id)]


@router.post("", status_code=201)
def create_application(body: ApplicationCreate, ctx: WorkspaceContext = Depends(workspace_access("developer")),
                       repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    # Synthetic apps are only allowed in demo workspaces, so test data cannot be
    # mixed into a real customer workspace.
    if body.is_synthetic and not ctx.is_demo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Synthetic applications are only allowed in demo workspaces")
    if ctx.is_demo and not body.is_synthetic:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Demo workspaces may only contain synthetic applications")
    key, prefix, key_hash = generate_ingestion_key()
    try:
        app = repo.create_application(ctx.workspace_id, ctx.user["id"], body.name, body.environment, body.framework,
                                      body.backend_url, body.is_synthetic, prefix, key_hash)
    except DuplicateError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An application with this name and environment already exists") from None
    app = {**app, "active_key_prefix": prefix}
    repo.audit(ctx.workspace_id, ctx.user["id"], "application.create", "application", str(app["id"]), {"environment": body.environment})
    return {"application": _out(app), "ingestion_key": key, "onboarding": _onboarding(app, settings)}


@router.get("/{application_id}")
def get_application(application_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")),
                    repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    app = repo.get_application(ctx.workspace_id, application_id)
    if not app:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return {"application": _out(app), "onboarding": _onboarding(app, settings)}


@router.post("/{application_id}/rotate-key")
def rotate_key(application_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("admin")),
               repo: Repository = Depends(get_repo)):
    key, prefix, key_hash = generate_ingestion_key()
    if not repo.rotate_ingestion_key(ctx.workspace_id, application_id, prefix, key_hash):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], "application.rotate_key", "application", str(application_id))
    return {"ingestion_key": key, "active_key_prefix": prefix}


@router.delete("/{application_id}", status_code=204)
def revoke_application(application_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("admin")),
                       repo: Repository = Depends(get_repo)):
    if not repo.revoke_application(ctx.workspace_id, application_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], "application.revoke", "application", str(application_id))
