"""
Terminal step of the correlation pipeline: persist the incident candidate as
the durable system-of-record row (Postgres `incidents` + `incident_services`
+ `incident_evidence`), and publish the same object to the
`incident.candidates` Kafka topic for the reasoning service (Phase 4) to
pick up. Both happen for every candidate - Postgres is the durable/queryable
record the dashboard reads, Kafka is what actually drives the reasoning
service's near-real-time consumption; neither alone is sufficient.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol

import psycopg
from aiokafka import AIOKafkaProducer

from incident_schemas import IncidentCandidate

logger = logging.getLogger(__name__)


class IncidentCandidateSink(Protocol):
    async def publish(self, candidate: IncidentCandidate) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class PostgresAndKafkaIncidentSink:
    def __init__(self, database_url: str, kafka_bootstrap_servers: str, kafka_topic: str) -> None:
        self._database_url = database_url
        self._kafka_bootstrap_servers = kafka_bootstrap_servers
        self._kafka_topic = kafka_topic
        self._conn: psycopg.Connection | None = None
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(
            None, lambda: psycopg.connect(self._database_url, autocommit=True)
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            enable_idempotence=True,
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
        if self._conn is not None:
            self._conn.close()

    async def publish(self, candidate: IncidentCandidate) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._persist, candidate)

        assert self._producer is not None
        await self._producer.send_and_wait(
            self._kafka_topic,
            value=candidate.model_dump(mode="json"),
            key=str(candidate.workspace_id),
        )
        logger.info(
            "incident_candidate_published",
            extra={
                "incident_id": str(candidate.id),
                "severity": candidate.suggested_severity.value,
                "service_count": len(candidate.affected_services),
                "evidence_count": len(candidate.evidence),
            },
        )

    def _persist(self, candidate: IncidentCandidate) -> None:
        assert self._conn is not None

        # affected_services already carries resolved service_id per service_name -
        # reuse that mapping rather than leaving incident_evidence.service_id NULL
        # for every row just because EvidenceItem itself only carries a name.
        service_id_by_name = {s.service_name: s.service_id for s in candidate.affected_services}

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incidents (id, workspace_id, status, severity, started_at)
                VALUES (%s, %s, 'candidate', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    str(candidate.id),
                    str(candidate.workspace_id),
                    candidate.suggested_severity.value,
                    candidate.window_start,
                ),
            )

            for service_anomaly in candidate.affected_services:
                cur.execute(
                    """
                    INSERT INTO incident_services (incident_id, service_id, anomaly_score)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (incident_id, service_id) DO UPDATE
                        SET anomaly_score = GREATEST(incident_services.anomaly_score, EXCLUDED.anomaly_score)
                    """,
                    (str(candidate.id), str(service_anomaly.service_id), service_anomaly.anomaly_score),
                )

            for item in candidate.evidence:
                resolved_service_id = service_id_by_name.get(item.service_name)
                cur.execute(
                    """
                    INSERT INTO incident_evidence
                        (id, incident_id, source_type, source_ref, service_id, snippet,
                         relevance_score, occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(item.id),
                        str(candidate.id),
                        item.source_type,
                        item.source_ref,
                        str(resolved_service_id) if resolved_service_id else None,
                        item.snippet,
                        item.relevance_score,
                        item.occurred_at,
                    ),
                )
