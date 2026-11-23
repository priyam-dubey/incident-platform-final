"""
POST /v1/telemetry - the entire public surface of the ingestion service.

Flow per event in the batch: fan out to (1) Kafka, for the correlation
engine to consume in near-real-time, and (2) ClickHouse, as the durable,
queryable raw-telemetry store. These are independent sinks with independent
failure modes - a ClickHouse hiccup should not block Kafka delivery (the
correlation engine's freshness matters more operationally than backfilling
a slow analytical store), so failures are tracked per-sink and a partial
failure is reported accurately rather than silently swallowed or treated as
a total failure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from app.tenant_auth import TenantContext, require_tenant
from app.sanitize import clean_attributes, clean_text
from app.config import Settings, get_settings
from app.metrics import EVENTS_INGESTED_TOTAL, EVENTS_PUBLISH_FAILURES_TOTAL
from app.rate_limiter import TokenBucketLimiter
from incident_schemas import TelemetryEnvelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["telemetry"])


class IngestResponse(BaseModel):
    accepted: int
    kafka_failures: int
    clickhouse_failures: int


def bind_and_sanitize(events: list, tenant: TenantContext, redact_enabled: bool) -> list:
    """Make the tenant authoritative, tag provenance, and strip secrets before storage."""
    out = []
    for e in events:
        update: dict = {"attributes": clean_attributes(dict(e.attributes), redact_enabled)}
        if tenant.tenant_bound:
            update["workspace_id"] = tenant.workspace_id
            update["attributes"].update({
                "platform.application_id": str(tenant.application_id),
                "platform.environment": tenant.environment or "",
                "platform.synthetic": tenant.is_synthetic,
            })
        if e.kind == "log":
            update["message"] = clean_text(e.message, 8192, redact_enabled)
        out.append(e.model_copy(update=update))
    return out


async def process_events(request: Request, events: list, idempotency_key: str, tenant: TenantContext,
                         settings: Settings) -> IngestResponse:
    limiter = request.app.state.rate_limiter
    if not limiter.allow(tenant.rate_key, cost=len(events)):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded for this API key")

    events = bind_and_sanitize(events, tenant, settings.redact_telemetry)
    publisher = request.app.state.event_publisher
    writer = request.app.state.telemetry_writer
    kafka_failures = clickhouse_failures = 0

    for event in events:
        try:
            await publisher.publish(settings.kafka_topic_telemetry_events, event)
            EVENTS_INGESTED_TOTAL.labels(event.kind).inc()
        except Exception:
            kafka_failures += 1
            EVENTS_PUBLISH_FAILURES_TOTAL.labels("kafka").inc()
            logger.error("event_publish_failed", extra={"idempotency_key": idempotency_key, "kind": event.kind})
        try:
            await writer.write(event)
        except Exception:
            clickhouse_failures += 1
            EVENTS_PUBLISH_FAILURES_TOTAL.labels("clickhouse").inc()
            logger.error("event_write_failed", extra={"idempotency_key": idempotency_key, "kind": event.kind})

    if settings.gateway_mode and events:
        await request.app.state.key_resolver.report_seen(tenant)

    logger.info("batch_ingested", extra={"idempotency_key": idempotency_key, "event_count": len(events),
                                          "kafka_failures": kafka_failures, "clickhouse_failures": clickhouse_failures})
    return IngestResponse(accepted=len(events) - kafka_failures, kafka_failures=kafka_failures,
                          clickhouse_failures=clickhouse_failures)


@router.post("/telemetry", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    request: Request,
    tenant: TenantContext = Depends(require_tenant),
    settings: Settings = Depends(get_settings),
) -> IngestResponse:
    body = await request.json()
    try:
        envelope = TelemetryEnvelope.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors())
    return await process_events(request, list(envelope.events), envelope.idempotency_key, tenant, settings)
