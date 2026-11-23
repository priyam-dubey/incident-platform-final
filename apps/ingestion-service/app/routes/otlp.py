"""
OTLP/HTTP (JSON) receiver. Point any OpenTelemetry HTTP exporter at
    {INGESTION_URL}/otlp     (exporters append /v1/traces, /v1/logs, /v1/metrics)
with header  X-Ingestion-Key: <application key>.

Protobuf bodies (application/x-protobuf) are not supported yet and get a clear 415;
the Node.js OTLP HTTP exporters default to JSON.
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import TypeAdapter, ValidationError

from app.config import Settings, get_settings
from app.otlp import OtlpError, convert_logs, convert_metrics, convert_traces
from app.routes.telemetry import process_events
from app.tenant_auth import TenantContext, require_tenant
from incident_schemas.telemetry import TelemetryEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/otlp/v1", tags=["otlp"])
_event_adapter = TypeAdapter(TelemetryEvent)


async def _handle(request: Request, converter, tenant: TenantContext, settings: Settings):
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Only OTLP/HTTP JSON (application/json) is supported. Use the http/json exporter.")
    raw = await request.body()
    if len(raw) > settings.max_body_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "OTLP payload too large")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not valid JSON") from None
    try:
        raw_events = converter(body)
    except OtlpError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid OTLP payload: {exc}") from None
    if len(raw_events) > settings.max_events_per_request:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Too many records ({len(raw_events)}); max {settings.max_events_per_request} per request")
    try:
        events = [_event_adapter.validate_python(e) for e in raw_events]
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, [
            {"loc": list(err["loc"]), "msg": err["msg"]} for err in exc.errors()[:10]]) from None
    if events:
        result = await process_events(request, events, hashlib.sha256(raw).hexdigest()[:32], tenant, settings)
        if result.kafka_failures:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Telemetry could not be queued; retry")
    return {"partialSuccess": {}}


@router.post("/traces")
async def traces(request: Request, tenant: TenantContext = Depends(require_tenant), settings: Settings = Depends(get_settings)):
    return await _handle(request, convert_traces, tenant, settings)


@router.post("/logs")
async def logs(request: Request, tenant: TenantContext = Depends(require_tenant), settings: Settings = Depends(get_settings)):
    return await _handle(request, convert_logs, tenant, settings)


@router.post("/metrics")
async def metrics(request: Request, tenant: TenantContext = Depends(require_tenant), settings: Settings = Depends(get_settings)):
    return await _handle(request, convert_metrics, tenant, settings)
