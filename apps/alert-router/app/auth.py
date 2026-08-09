"""
Machine-client authentication for the alert-router's HTTP API. Same
constant-time comparison pattern as apps/ingestion-service/app/auth.py -
duplicated rather than shared as a package because the two services'
header/config names differ slightly and the logic is a handful of lines;
promoting this to a shared package is a reasonable Phase 7+ refactor once a
third consumer needs it too (rule of three).

Human reviewer identity (who accepted/rejected a hypothesis) is separate
from this API-key check: the dashboard authenticates end users via its own
session (Phase 6) and forwards the reviewer's identity as X-Reviewer-Email,
trusted here because the dashboard backend is the only holder of a valid API
key. A production system would eventually verify this end-to-end (e.g. a
signed JWT from the dashboard's session instead of a trusted header), noted
here rather than glossed over.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def _constant_time_in(candidate: str, valid_keys: set[str]) -> bool:
    return any(hmac.compare_digest(candidate, key) for key in valid_keys)


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Missing {settings.api_key_header} header")
    if not _constant_time_in(x_api_key, settings.valid_api_keys):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key


async def require_reviewer_identity(
    x_reviewer_email: str | None = Header(default=None, alias="X-Reviewer-Email"),
) -> str:
    if not x_reviewer_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Reviewer-Email header is required to attribute a verdict to a human",
        )
    return x_reviewer_email
