"""
Application entrypoint. Wires up config, logging, the Kafka producer and
ClickHouse writer (started/stopped via FastAPI's lifespan context so
connections are established once at startup and drained cleanly at
shutdown, not per-request), and the route table.

Dependencies are injected via factories rather than hardcoded inside
lifespan, so tests can swap in fakes without touching real infrastructure -
the factories default to the real Kafka/ClickHouse implementations, but
create_app(event_publisher_factory=..., telemetry_writer_factory=...) lets
tests substitute fakes while exercising the exact same startup/shutdown
lifecycle as production.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.clickhouse_writer import ClickHouseTelemetryWriter, TelemetryWriter
from app.config import Settings, get_settings
from app.kafka_producer import EventPublisher, KafkaEventPublisher
from app.logging_config import configure_logging
from app.metrics import PrometheusMiddleware, metrics_response
from app.rate_limiter import TokenBucketLimiter
from app.routes.telemetry import router as telemetry_router

logger = logging.getLogger(__name__)

EventPublisherFactory = Callable[[Settings], EventPublisher]
TelemetryWriterFactory = Callable[[Settings], TelemetryWriter]


def _default_event_publisher(settings: Settings) -> EventPublisher:
    return KafkaEventPublisher(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks=settings.kafka_producer_acks,
        linger_ms=settings.kafka_producer_linger_ms,
    )


def _default_telemetry_writer(settings: Settings) -> TelemetryWriter:
    return ClickHouseTelemetryWriter(
        url=settings.clickhouse_url,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_db,
    )


def _build_lifespan(
    event_publisher_factory: EventPublisherFactory,
    telemetry_writer_factory: TelemetryWriterFactory,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        configure_logging(settings.log_level)

        app.state.event_publisher = event_publisher_factory(settings)
        app.state.telemetry_writer = telemetry_writer_factory(settings)
        app.state.rate_limiter = TokenBucketLimiter(
            rate_per_second=settings.rate_limit_events_per_second,
            burst=settings.rate_limit_burst,
        )

        await app.state.event_publisher.start()
        await app.state.telemetry_writer.start()
        logger.info("ingestion_service_started", extra={"environment": settings.environment})

        yield

        await app.state.telemetry_writer.stop()
        await app.state.event_publisher.stop()
        logger.info("ingestion_service_stopped")

    return lifespan


def create_app(
    event_publisher_factory: EventPublisherFactory = _default_event_publisher,
    telemetry_writer_factory: TelemetryWriterFactory = _default_telemetry_writer,
) -> FastAPI:
    app = FastAPI(
        title="Incident Platform - Ingestion Service",
        version="0.1.0",
        lifespan=_build_lifespan(event_publisher_factory, telemetry_writer_factory),
    )

    app.include_router(telemetry_router)
    app.add_middleware(PrometheusMiddleware)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return metrics_response()

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()

