"""
Telemetry wire contracts.

These are the schemas the ingestion service validates every inbound event
against, and the schemas the correlation engine reads back out of Kafka.
Deliberately modeled close to OpenTelemetry's log/metric/span shape so a real
OTel Collector can be pointed at the ingestion service with a thin exporter
adapter, rather than requiring a bespoke SDK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    trace = "trace"
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"
    fatal = "fatal"


class _TelemetryBase(BaseModel):
    workspace_id: UUID
    service_name: Annotated[str, Field(min_length=1, max_length=200)]
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # Refuse naive timestamps outright rather than silently assuming UTC -
            # a silently-wrong timestamp corrupts every downstream correlation window.
            raise ValueError(
                "timestamp must be timezone-aware (e.g. end with 'Z' or '+00:00')"
            )
        return v.astimezone(timezone.utc)


class LogEvent(_TelemetryBase):
    kind: Literal["log"] = "log"
    severity: Severity
    message: Annotated[str, Field(min_length=1, max_length=8192)]
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class MetricEvent(_TelemetryBase):
    kind: Literal["metric"] = "metric"
    metric_name: Annotated[str, Field(min_length=1, max_length=200)]
    value: float
    unit: str | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class TraceSpanEvent(_TelemetryBase):
    kind: Literal["trace_span"] = "trace_span"
    trace_id: Annotated[str, Field(min_length=1, max_length=64)]
    span_id: Annotated[str, Field(min_length=1, max_length=64)]
    parent_span_id: str | None = None
    operation_name: Annotated[str, Field(min_length=1, max_length=200)]
    duration_ms: Annotated[float, Field(ge=0)]
    status: Literal["ok", "error", "unset"] = "unset"
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


TelemetryEvent = Annotated[
    Union[LogEvent, MetricEvent, TraceSpanEvent],
    Field(discriminator="kind"),
]


class TelemetryEnvelope(BaseModel):
    """
    The actual POST body accepted by the ingestion service. Batched, because
    real telemetry clients batch - accepting one-event-per-request at
    production log volume would make the ingestion API the bottleneck.
    """

    events: Annotated[list[TelemetryEvent], Field(min_length=1, max_length=1000)]
    # Set by the client SDK; used for exactly-once dedup on the consumer side.
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
