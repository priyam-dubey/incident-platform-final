"""
Tenant-aware ingestion authentication.

Gateway mode: the presented key is verified by the API gateway, which returns the
authoritative workspace + application. Ingestion then OVERWRITES any workspace_id in
the payload, so one tenant's key can never write into another tenant.

Static mode (development only): legacy key list; the payload's workspace_id is trusted.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import httpx
from fastapi import Depends, Header, HTTPException, Request, status

from app.auth import _constant_time_in
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantContext:
    rate_key: str
    workspace_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    application_name: str | None = None
    environment: str | None = None
    is_synthetic: bool = False

    @property
    def tenant_bound(self) -> bool:
        return self.workspace_id is not None


class GatewayKeyResolver:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, clock=time.monotonic) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._clock = clock
        self._cache: dict[str, tuple[float, TenantContext | None]] = {}
        self._seen_reported: dict[str, float] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, key: str) -> TenantContext | None:
        now = self._clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        try:
            r = await self._client.post(
                f"{self._s.gateway_url.rstrip('/')}/internal/v1/ingestion-keys/verify",
                json={"key": key}, headers={"X-Internal-Token": self._s.internal_api_token},
            )
        except httpx.HTTPError:
            logger.error("gateway_unreachable_for_key_verification")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Key verification temporarily unavailable") from None
        if r.status_code == 401:
            self._remember(key, None, self._s.key_negative_cache_ttl_seconds)
            return None
        if r.status_code != 200:
            logger.error("gateway_verify_unexpected_status", extra={"status": r.status_code})
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Key verification temporarily unavailable")
        d = r.json()
        ctx = TenantContext(
            rate_key=d["application_id"], workspace_id=uuid.UUID(d["workspace_id"]),
            application_id=uuid.UUID(d["application_id"]), application_name=d["application_name"],
            environment=d["environment"], is_synthetic=bool(d.get("is_synthetic")),
        )
        self._remember(key, ctx, self._s.key_cache_ttl_seconds)
        return ctx

    def _remember(self, key: str, ctx: TenantContext | None, ttl: float) -> None:
        if len(self._cache) > 10_000:
            self._cache.clear()
        self._cache[key] = (self._clock() + ttl, ctx)

    async def report_seen(self, ctx: TenantContext) -> None:
        """Tell the gateway an application sent telemetry (throttled to once/30s per app)."""
        if ctx.application_id is None:
            return
        k, now = str(ctx.application_id), self._clock()
        if now - self._seen_reported.get(k, -1e9) < 30:
            return
        self._seen_reported[k] = now
        try:
            await self._client.post(
                f"{self._s.gateway_url.rstrip('/')}/internal/v1/applications/telemetry-seen",
                json={"application_id": k}, headers={"X-Internal-Token": self._s.internal_api_token},
            )
        except httpx.HTTPError:
            logger.warning("telemetry_seen_report_failed")


async def require_tenant(
    request: Request,
    x_ingestion_key: str | None = Header(default=None, alias="X-Ingestion-Key"),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    if not x_ingestion_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Missing {settings.ingestion_api_key_header} header")
    if settings.gateway_mode:
        resolver: GatewayKeyResolver = request.app.state.key_resolver
        ctx = await resolver.resolve(x_ingestion_key)
        if ctx is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        return ctx
    if not _constant_time_in(x_ingestion_key, settings.valid_api_keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return TenantContext(rate_key=x_ingestion_key)
