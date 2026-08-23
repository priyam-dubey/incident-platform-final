"""
Kafka (Redpanda) producer wrapper.

Every event is published individually (not the whole batch as one message) so
the correlation engine (Phase 3) can consume and window per-event without
first unpacking client-side batches - the batching in the HTTP API is purely
a network-efficiency concern for the client, not something downstream
consumers should need to know about.

Partition key is workspace_id: this guarantees all of one workspace's events
land on the same partition and are consumed in emission order, which the
correlation engine's windowed aggregation depends on. Cross-workspace
ordering is never guaranteed or required.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from aiokafka import AIOKafkaProducer

from incident_schemas import LogEvent, MetricEvent, TraceSpanEvent

logger = logging.getLogger(__name__)

TelemetryEventUnion = LogEvent | MetricEvent | TraceSpanEvent


class EventPublisher(Protocol):
    """Interface the route handler depends on - lets tests inject a fake."""

    async def publish(self, topic: str, event: TelemetryEventUnion) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class KafkaEventPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        acks: str = "all",
        linger_ms: int = 20,
        client_kwargs: dict | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._acks = acks
        self._linger_ms = linger_ms
        self._client_kwargs = client_kwargs or {}
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            acks=self._acks,
            linger_ms=self._linger_ms,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            enable_idempotence=True,  # producer-level exactly-once against broker retries
            **self._client_kwargs,
        )
        await self._producer.start()
        logger.info("kafka_producer_started", extra={"bootstrap_servers": self._bootstrap_servers})

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            logger.info("kafka_producer_stopped")

    async def publish(self, topic: str, event: TelemetryEventUnion) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaEventPublisher.start() must be called before publish()")

        partition_key = str(event.workspace_id)
        payload = event.model_dump(mode="json")

        try:
            await self._producer.send_and_wait(topic, value=payload, key=partition_key)
        except Exception:
            logger.exception(
                "kafka_publish_failed",
                extra={"topic": topic, "workspace_id": partition_key, "kind": event.kind},
            )
            raise
