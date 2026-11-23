"""Service-to-service endpoints (ingestion edge -> gateway). Not for browsers."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.deps import get_repo
from app.repository import Repository
from app.security import constant_time_equal, parse_ingestion_key, sha256_hex

router = APIRouter(prefix="/internal/v1", tags=["internal"])


def require_internal(x_internal_token: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> None:
    if not settings.internal_api_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal API not configured")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")


class VerifyKeyRequest(BaseModel):
    key: str = Field(min_length=10, max_length=200)


@router.post("/ingestion-keys/verify", dependencies=[Depends(require_internal)])
def verify_key(body: VerifyKeyRequest, repo: Repository = Depends(get_repo)):
    """Resolves an application ingestion key to its workspace + application.

    The workspace_id returned here is authoritative: ingestion must overwrite any
    workspace_id supplied by the client, so a key can never write into another tenant.
    """
    prefix = parse_ingestion_key(body.key)
    row = repo.lookup_ingestion_key(prefix) if prefix else None
    if row is None or not constant_time_equal(sha256_hex(body.key), row["key_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid ingestion key")
    repo.touch_key(row["key_id"], row["application_id"])
    return {"workspace_id": str(row["workspace_id"]), "application_id": str(row["application_id"]),
            "application_name": row["application_name"], "environment": row["environment"], "is_synthetic": row["is_synthetic"]}


class TelemetrySeenRequest(BaseModel):
    application_id: str


@router.post("/applications/telemetry-seen", status_code=204, dependencies=[Depends(require_internal)])
def telemetry_seen(body: TelemetrySeenRequest, repo: Repository = Depends(get_repo)):
    import uuid
    repo.mark_telemetry_received(uuid.UUID(body.application_id))
