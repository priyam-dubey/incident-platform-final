"""
API key authentication for machine-to-machine ingestion clients.

Deliberately simple (a validated set of keys, checked in constant time) -
this is the ingestion edge, not the customer-facing dashboard (which will use
proper OIDC/session auth in Phase 6). Keys are rotated by adding a new key to
INGESTION_VALID_API_KEYS alongside the old one, deploying, confirming the new
key is in use, then removing the old one - zero-downtime rotation.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def _constant_time_in(candidate: str, valid_keys: set[str]) -> bool:
    # Iterating and using hmac.compare_digest per key avoids leaking timing
    # information about *which* key (if any) partially matched.
    return any(hmac.compare_digest(candidate, key) for key in valid_keys)


async def require_api_key(
    x_ingestion_key: str | None = Header(default=None, alias="X-Ingestion-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    if not x_ingestion_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {settings.ingestion_api_key_header} header",
        )
    if not _constant_time_in(x_ingestion_key, settings.valid_api_keys):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_ingestion_key
