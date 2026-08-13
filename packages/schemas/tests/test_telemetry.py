from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from incident_schemas import LogEvent, MetricEvent, TelemetryEnvelope, TraceSpanEvent  # noqa: E402


WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def test_log_event_accepts_valid_payload() -> None:
    event = LogEvent(
        workspace_id=WORKSPACE_ID,
        service_name="checkout-api",
        timestamp="2026-08-05T10:00:00Z",
        severity="error",
        message="payment gateway timeout",
    )
    assert event.severity.value == "error"
    assert event.timestamp.tzinfo is not None


def test_log_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        LogEvent(
            workspace_id=WORKSPACE_ID,
            service_name="checkout-api",
            timestamp=datetime(2026, 8, 5, 10, 0, 0),  # no tzinfo
            severity="error",
            message="payment gateway timeout",
        )


def test_log_event_normalizes_timestamp_to_utc() -> None:
    event = LogEvent(
        workspace_id=WORKSPACE_ID,
        service_name="checkout-api",
        timestamp="2026-08-05T10:00:00+05:30",
        severity="info",
        message="ok",
    )
    assert event.timestamp.utcoffset() == timezone.utc.utcoffset(None)


def test_log_event_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        LogEvent(
            workspace_id=WORKSPACE_ID,
            service_name="checkout-api",
            timestamp="2026-08-05T10:00:00Z",
            severity="info",
            message="",
        )


def test_metric_event_requires_numeric_value() -> None:
    with pytest.raises(ValidationError):
        MetricEvent(
            workspace_id=WORKSPACE_ID,
            service_name="checkout-api",
            timestamp="2026-08-05T10:00:00Z",
            metric_name="latency_ms",
            value="not-a-number",
        )


def test_trace_span_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        TraceSpanEvent(
            workspace_id=WORKSPACE_ID,
            service_name="checkout-api",
            timestamp="2026-08-05T10:00:00Z",
            trace_id="abc",
            span_id="def",
            operation_name="POST /charge",
            duration_ms=-5,
        )


def test_envelope_discriminates_event_kind_correctly() -> None:
    envelope = TelemetryEnvelope(
        idempotency_key="batch-1",
        events=[
            {
                "kind": "log",
                "workspace_id": WORKSPACE_ID,
                "service_name": "checkout-api",
                "timestamp": "2026-08-05T10:00:00Z",
                "severity": "error",
                "message": "timeout",
            },
            {
                "kind": "metric",
                "workspace_id": WORKSPACE_ID,
                "service_name": "checkout-api",
                "timestamp": "2026-08-05T10:00:00Z",
                "metric_name": "p99_latency_ms",
                "value": 812.3,
            },
        ],
    )
    assert isinstance(envelope.events[0], LogEvent)
    assert isinstance(envelope.events[1], MetricEvent)


def test_envelope_rejects_empty_batch() -> None:
    with pytest.raises(ValidationError):
        TelemetryEnvelope(idempotency_key="batch-1", events=[])


def test_envelope_rejects_batch_over_max_size() -> None:
    event = {
        "kind": "log",
        "workspace_id": WORKSPACE_ID,
        "service_name": "checkout-api",
        "timestamp": "2026-08-05T10:00:00Z",
        "severity": "info",
        "message": "ok",
    }
    with pytest.raises(ValidationError):
        TelemetryEnvelope(idempotency_key="batch-1", events=[event] * 1001)
