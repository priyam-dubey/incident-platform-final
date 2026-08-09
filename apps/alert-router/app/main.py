"""
Two responsibilities running in one process: the HTTP review API (routes/
incidents.py) and a Kafka consumer of `incident.candidates` that immediately
escalates high/critical incidents to Slack/PagerDuty (escalation_policy.py +
alert_dispatcher.py) - the human review step happens on the dashboard's own
timeline, but paging on-call for a critical incident can't wait for someone
to open a browser tab.

Dependency injection mirrors the other services: create_app() accepts
factories for the repository and alert senders, defaulting to real
Postgres/Slack/PagerDuty, so tests can substitute fakes while exercising the
real FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Callable

import psycopg
from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

from app.alert_dispatcher import AlertDispatcher
from app.alert_senders import PagerDutyAlertSender, SlackAlertSender
from app.config import Settings, get_settings
from app.escalation_policy import channels_for_severity
from app.logging_config import configure_logging
from app.metrics import ALERTS_DISPATCHED_TOTAL, PrometheusMiddleware, metrics_response
from app.repository import IncidentRepository, PostgresIncidentRepository
from app.routes.incidents import router as incidents_router
from incident_schemas import IncidentCandidate

logger = logging.getLogger(__name__)

RepositoryFactory = Callable[[Settings], IncidentRepository]


def _default_repository_factory(settings: Settings) -> IncidentRepository:
    return PostgresIncidentRepository(settings.database_url)


class PostgresAlertEventStore:
    """Persists every alert attempt to `alert_events` - the audit trail."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn: psycopg.Connection | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(
            None, lambda: psycopg.connect(self._database_url, autocommit=True)
        )

    async def stop(self) -> None:
        if self._conn is not None:
            self._conn.close()

    async def record_attempt(self, incident_id: str, channel: str, status: str, error: str | None) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._record_sync, incident_id, channel, status, error)

    def _record_sync(self, incident_id: str, channel: str, status: str, error: str | None) -> None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (incident_id, channel, status, attempts, last_error, sent_at)
                VALUES (%s, %s, %s, 1, %s, CASE WHEN %s = 'sent' THEN now() ELSE NULL END)
                """,
                (incident_id, channel, status, error, status),
            )


async def _escalation_consume_loop(
    consumer: AIOKafkaConsumer, dispatcher: AlertDispatcher
) -> None:
    async for message in consumer:
        try:
            candidate = IncidentCandidate.model_validate(json.loads(message.value))
            channels = channels_for_severity(candidate.suggested_severity)
            if not channels:
                continue

            summary = (
                f"{len(candidate.affected_services)} service(s) affected: "
                f"{', '.join(s.service_name for s in candidate.affected_services)}"
            )
            results = await dispatcher.dispatch(
                str(candidate.id), candidate.suggested_severity, summary, channels
            )
            for channel, succeeded in results.items():
                ALERTS_DISPATCHED_TOTAL.labels(channel, "sent" if succeeded else "failed").inc()
        except Exception:
            logger.exception("escalation_processing_failed")


def _build_lifespan(repository_factory: RepositoryFactory, enable_escalation_consumer: bool):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        configure_logging(settings.log_level)

        repository = repository_factory(settings)
        await repository.start()
        app.state.repository = repository

        consume_task = None
        event_store = None
        consumer = None

        if enable_escalation_consumer:
            event_store = PostgresAlertEventStore(settings.database_url)
            await event_store.start()

            senders = {}
            if settings.slack_webhook_url:
                senders["slack"] = SlackAlertSender(settings.slack_webhook_url)
            if settings.pagerduty_routing_key:
                senders["pagerduty"] = PagerDutyAlertSender(settings.pagerduty_routing_key)

            dispatcher = AlertDispatcher(
                senders, event_store, settings.alert_max_attempts, settings.alert_base_backoff_seconds
            )

            consumer = AIOKafkaConsumer(
                settings.kafka_topic_incident_candidates,
                bootstrap_servers=settings.kafka_bootstrap_servers,
                group_id=settings.kafka_consumer_group_alerts,
                enable_auto_commit=True,
                auto_offset_reset="latest",
            )
            await consumer.start()
            consume_task = asyncio.create_task(_escalation_consume_loop(consumer, dispatcher))

        logger.info("alert_router_started", extra={"environment": settings.environment})

        yield

        if consume_task is not None:
            consume_task.cancel()
        if consumer is not None:
            await consumer.stop()
        if event_store is not None:
            await event_store.stop()
        await repository.stop()
        logger.info("alert_router_stopped")

    return lifespan


def create_app(
    repository_factory: RepositoryFactory = _default_repository_factory,
    enable_escalation_consumer: bool = True,
) -> FastAPI:
    app = FastAPI(
        title="Incident Platform - Alert Router",
        version="0.1.0",
        lifespan=_build_lifespan(repository_factory, enable_escalation_consumer),
    )
    app.include_router(incidents_router)
    app.add_middleware(PrometheusMiddleware)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return metrics_response()

    return app


app = create_app()
