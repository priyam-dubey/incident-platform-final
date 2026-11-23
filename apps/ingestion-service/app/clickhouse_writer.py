"""
ClickHouse writer for raw telemetry.

clickhouse-connect's client is synchronous; ClickHouse inserts are also far
more efficient batched (one INSERT of 500 rows beats 500 single-row INSERTs
by orders of magnitude at this volume), so this buffers events in memory and
flushes on a size or time trigger, running the actual (blocking) insert call
in a thread pool so it never blocks the event loop the FastAPI routes run on.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import clickhouse_connect

from incident_schemas import LogEvent, MetricEvent, TraceSpanEvent
from incident_schemas.clickhouse_ddl import CREATE_TABLE_SQL, MIGRATION_SQL, TELEMETRY_TABLE

logger = logging.getLogger(__name__)

TelemetryEventUnion = LogEvent | MetricEvent | TraceSpanEvent

_TABLE = TELEMETRY_TABLE
_CREATE_TABLE_SQL = CREATE_TABLE_SQL


def _event_to_row(event: TelemetryEventUnion) -> dict:
    import json

    row = {
        "workspace_id": str(event.workspace_id),
        "service_name": event.service_name,
        "kind": event.kind,
        "timestamp": event.timestamp,
        "severity": "",
        "message": "",
        "metric_name": "",
        "value": None,
        "trace_id": "",
        "span_id": "",
        "operation_name": "",
        "duration_ms": None,
        "status": "",
        "attributes": "{}",
        "parent_span_id": "",
    }

    if isinstance(event, LogEvent):
        row.update(
            severity=event.severity.value,
            message=event.message,
            trace_id=event.trace_id or "",
            span_id=event.span_id or "",
            attributes=json.dumps(event.attributes, default=str),
        )
    elif isinstance(event, MetricEvent):
        row.update(
            metric_name=event.metric_name,
            value=event.value,
            attributes=json.dumps(event.attributes, default=str),
        )
    elif isinstance(event, TraceSpanEvent):
        row.update(
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id or "",
            operation_name=event.operation_name,
            duration_ms=event.duration_ms,
            status=event.status,
            attributes=json.dumps(event.attributes, default=str),
        )
    return row


class TelemetryWriter(Protocol):
    async def write(self, event: TelemetryEventUnion) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class NullTelemetryWriter:
    """No-op TelemetryWriter for when ClickHouse isn't deployed.

    Telemetry still flows into Kafka regardless (that's what correlation-
    engine actually consumes) - this only skips the raw-telemetry durable
    store, which nothing downstream currently reads from. Implements the
    same TelemetryWriter protocol as ClickHouseTelemetryWriter so main.py's
    factory wiring and every call site is unchanged.
    """

    async def start(self) -> None:
        logger.warning(
            "clickhouse_disabled - raw telemetry store inactive, "
            "events still flow to Kafka for correlation-engine"
        )

    async def stop(self) -> None:
        pass

    async def write(self, event: TelemetryEventUnion) -> None:
        pass


class ClickHouseTelemetryWriter:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        database: str,
        flush_size: int = 500,
        flush_interval_seconds: float = 2.0,
    ) -> None:
        self._url = url
        self._username = username
        self._password = password
        self._database = database
        self._flush_size = flush_size
        self._flush_interval = flush_interval_seconds

        self._client = None
        self._buffer: list[dict] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self._url)
        host = parsed.hostname or "localhost"
        # ClickHouse Cloud terminates TLS on 8443 and requires secure=True;
        # local Docker ClickHouse uses plain HTTP on 8123. Both scheme
        # ("https://...") and the conventional 8443 port are honored, so a
        # CLICKHOUSE_URL of either form works without further config.
        secure = parsed.scheme == "https" or parsed.port == 8443
        port = parsed.port or (8443 if secure else 8123)

        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(
            None,
            lambda: clickhouse_connect.get_client(
                host=host,
                port=port,
                username=self._username,
                password=self._password,
                database=self._database,
                secure=secure,
            ),
        )
        await loop.run_in_executor(None, lambda: self._client.command(_CREATE_TABLE_SQL))
        for statement in MIGRATION_SQL:  # upgrade tables created before derived columns existed
            await loop.run_in_executor(None, lambda sql=statement: self._client.command(sql))
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("clickhouse_writer_started", extra={"database": self._database})

    async def stop(self) -> None:
        self._stopped.set()
        if self._flush_task is not None:
            await self._flush_task
        await self._flush()
        logger.info("clickhouse_writer_stopped")

    async def write(self, event: TelemetryEventUnion) -> None:
        row = _event_to_row(event)
        async with self._buffer_lock:
            self._buffer.append(row)
            should_flush = len(self._buffer) >= self._flush_size
        if should_flush:
            await self._flush()

    async def _flush_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._flush_interval)
            except asyncio.TimeoutError:
                pass
            await self._flush()

    async def _flush(self) -> None:
        async with self._buffer_lock:
            if not self._buffer:
                return
            rows, self._buffer = self._buffer, []

        columns = list(rows[0].keys())
        data = [[row[c] for c in columns] for row in rows]

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._client.insert(_TABLE, data, column_names=columns)
            )
            logger.info("clickhouse_flush_succeeded", extra={"row_count": len(rows)})
        except Exception:
            logger.exception("clickhouse_flush_failed", extra={"row_count": len(rows)})
            raise
