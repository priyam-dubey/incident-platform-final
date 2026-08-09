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

from app.auth import require_api_key
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


def get_rate_limiter(request: Request) -> TokenBucketLimiter:
    return request.app.state.rate_limiter


@router.post("/telemetry", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    request: Request,
    api_key: str = Depends(require_api_key),
    settings: Settings = Depends(get_settings),
    limiter: TokenBucketLimiter = Depends(get_rate_limiter),
) -> IngestResponse:
    body = await request.json()

    try:
        envelope = TelemetryEnvelope.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors())

    if not limiter.allow(api_key, cost=len(envelope.events)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this API key",
        )

    publisher = request.app.state.event_publisher
    writer = request.app.state.telemetry_writer

    kafka_failures = 0
    clickhouse_failures = 0

    for event in envelope.events:
        try:
            await publisher.publish(settings.kafka_topic_telemetry_events, event)
            EVENTS_INGESTED_TOTAL.labels(event.kind).inc()
        except Exception:
            kafka_failures += 1
            EVENTS_PUBLISH_FAILURES_TOTAL.labels("kafka").inc()
            logger.error(
                "event_publish_failed",
                extra={"idempotency_key": envelope.idempotency_key, "kind": event.kind},
            )

        try:
            await writer.write(event)
        except Exception:
            clickhouse_failures += 1
            EVENTS_PUBLISH_FAILURES_TOTAL.labels("clickhouse").inc()
            logger.error(
                "event_write_failed",
                extra={"idempotency_key": envelope.idempotency_key, "kind": event.kind},
            )

    accepted = len(envelope.events) - max(kafka_failures, 0)

    logger.info(
        "batch_ingested",
        extra={
            "idempotency_key": envelope.idempotency_key,
            "event_count": len(envelope.events),
            "kafka_failures": kafka_failures,
            "clickhouse_failures": clickhouse_failures,
        },
    )

    return IngestResponse(
        accepted=accepted,
        kafka_failures=kafka_failures,
        clickhouse_failures=clickhouse_failures,
    )
