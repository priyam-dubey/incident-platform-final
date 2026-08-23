"""
Worker entrypoint. Not a request/response API - this is a long-running
consumer process that reads apart from apps/ingestion-service's HTTP surface
entirely. It exposes a tiny FastAPI app (healthz + basic counters) purely for
container health checks and operational visibility, run alongside the
consume loop via asyncio, not as the primary interface.

Deserialization: telemetry.events messages are JSON with a `kind` discriminator
field, the same shape TelemetryEnvelope.events entries have - reusing the
incident_schemas TelemetryEvent union for parsing means the ingestion service
and correlation engine can never silently drift on wire format, since both
depend on the exact same package.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI
from pydantic import TypeAdapter

from app.anomaly_detector import AnomalyDetector
from app.cluster_engine import ClusterEngine
from app.config import get_settings
from app.evidence_buffer import EvidenceBuffer
from app.incident_writer import PostgresAndKafkaIncidentSink
from app.logging_config import configure_logging
from app.metrics import ANOMALIES_DETECTED_TOTAL, INCIDENT_CANDIDATES_EMITTED_TOTAL, metrics_response
from app.pipeline import CorrelationPipeline
from app.service_registry import PostgresServiceRegistry
from incident_schemas.telemetry import LogEvent, MetricEvent, TelemetryEvent, TraceSpanEvent

logger = logging.getLogger(__name__)

_event_adapter: TypeAdapter = TypeAdapter(TelemetryEvent)

_stats = {"events_consumed": 0, "ticks_run": 0, "candidates_emitted": 0}


async def _dispatch(pipeline: CorrelationPipeline, raw_value: bytes) -> None:
    payload = json.loads(raw_value)
    event = _event_adapter.validate_python(payload)

    if isinstance(event, MetricEvent):
        await pipeline.handle_metric_event(event)
    elif isinstance(event, LogEvent):
        await pipeline.handle_log_event(event)
    elif isinstance(event, TraceSpanEvent):
        await pipeline.handle_trace_event(event)

    _stats["events_consumed"] += 1


async def _consume_loop(pipeline: CorrelationPipeline, consumer: AIOKafkaConsumer) -> None:
    async for message in consumer:
        try:
            await _dispatch(pipeline, message.value)
        except Exception:
            # A single malformed/unparseable message must never kill the
            # consumer loop - log it and keep processing everything after it.
            logger.exception("event_dispatch_failed", extra={"offset": message.offset})


async def _tick_loop(pipeline: CorrelationPipeline, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            emitted = await pipeline.tick(datetime.now(timezone.utc))
            _stats["ticks_run"] += 1
            _stats["candidates_emitted"] += len(emitted)
            INCIDENT_CANDIDATES_EMITTED_TOTAL.inc(len(emitted))
            for candidate in emitted:
                for service_anomaly in candidate.affected_services:
                    ANOMALIES_DETECTED_TOTAL.labels(service_anomaly.service_name).inc()
        except Exception:
            logger.exception("tick_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    service_registry = PostgresServiceRegistry(settings.database_url)
    candidate_sink = PostgresAndKafkaIncidentSink(
        database_url=settings.database_url,
        kafka_bootstrap_servers=settings.kafka_bootstrap_servers,
        kafka_topic=settings.kafka_topic_incident_candidates,
        kafka_client_kwargs=settings.kafka_client_kwargs,
    )
    await service_registry.start()
    await candidate_sink.start()

    pipeline = CorrelationPipeline(
        anomaly_detector=AnomalyDetector(
            zscore_threshold=settings.anomaly_zscore_threshold,
            window_size=settings.anomaly_window_size,
            min_samples=settings.anomaly_min_samples,
        ),
        cluster_engine=ClusterEngine(correlation_window_seconds=settings.correlation_window_seconds),
        evidence_buffer=EvidenceBuffer(),
        service_registry=service_registry,
        candidate_sink=candidate_sink,
        correlation_window_seconds=settings.correlation_window_seconds,
    )
    app.state.pipeline = pipeline
    app.state.stats = _stats

    consumer = AIOKafkaConsumer(
        settings.kafka_topic_telemetry_events,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_correlation,
        enable_auto_commit=True,
        auto_offset_reset="latest",
        **settings.kafka_client_kwargs,
    )
    await consumer.start()

    consume_task = asyncio.create_task(_consume_loop(pipeline, consumer))
    tick_task = asyncio.create_task(_tick_loop(pipeline, settings.correlation_window_seconds))

    logger.info("correlation_engine_started", extra={"environment": settings.environment})

    yield

    consume_task.cancel()
    tick_task.cancel()
    await consumer.stop()
    await candidate_sink.stop()
    await service_registry.stop()
    logger.info("correlation_engine_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Incident Platform - Correlation Engine", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/stats", tags=["ops"])
    async def stats() -> dict:
        return dict(_stats)

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return metrics_response()

    return app


app = create_app()
