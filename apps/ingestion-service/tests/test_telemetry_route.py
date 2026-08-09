from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from tests.conftest import FakeEventPublisher, FakeTelemetryWriter

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
VALID_KEY = "dev-local-ingestion-key"  # matches Settings default


def _valid_envelope(n: int = 1) -> dict:
    return {
        "idempotency_key": "batch-abc",
        "events": [
            {
                "kind": "log",
                "workspace_id": WORKSPACE_ID,
                "service_name": "checkout-api",
                "timestamp": "2026-08-05T10:00:00Z",
                "severity": "error",
                "message": f"timeout #{i}",
            }
            for i in range(n)
        ],
    }


def test_healthz_does_not_require_auth(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_rejects_missing_api_key(client: TestClient) -> None:
    response = client.post("/v1/telemetry", json=_valid_envelope())
    assert response.status_code == 401


def test_ingest_rejects_invalid_api_key(client: TestClient) -> None:
    response = client.post(
        "/v1/telemetry", json=_valid_envelope(), headers={"X-Ingestion-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_ingest_accepts_valid_batch(
    client: TestClient, fake_publisher: FakeEventPublisher, fake_writer: FakeTelemetryWriter
) -> None:
    response = client.post(
        "/v1/telemetry", json=_valid_envelope(n=3), headers={"X-Ingestion-Key": VALID_KEY}
    )

    assert response.status_code == 202
    body = response.json()
    assert body == {"accepted": 3, "kafka_failures": 0, "clickhouse_failures": 0}
    assert len(fake_publisher.published) == 3
    assert len(fake_writer.written) == 3


def test_ingest_rejects_malformed_payload_with_422(client: TestClient) -> None:
    response = client.post(
        "/v1/telemetry",
        json={"idempotency_key": "x", "events": []},  # empty batch is invalid
        headers={"X-Ingestion-Key": VALID_KEY},
    )
    assert response.status_code == 422


def test_ingest_rejects_unknown_event_kind(client: TestClient) -> None:
    payload = {
        "idempotency_key": "x",
        "events": [
            {
                "kind": "smoke_signal",
                "workspace_id": WORKSPACE_ID,
                "service_name": "checkout-api",
                "timestamp": "2026-08-05T10:00:00Z",
            }
        ],
    }
    response = client.post(
        "/v1/telemetry", json=payload, headers={"X-Ingestion-Key": VALID_KEY}
    )
    assert response.status_code == 422


def test_kafka_failure_is_reported_but_clickhouse_write_still_happens(
    fake_writer: FakeTelemetryWriter,
) -> None:
    failing_publisher = FakeEventPublisher(fail_on_kinds={"log"})
    app = create_app(
        event_publisher_factory=lambda settings: failing_publisher,
        telemetry_writer_factory=lambda settings: fake_writer,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/telemetry", json=_valid_envelope(n=2), headers={"X-Ingestion-Key": VALID_KEY}
        )

    assert response.status_code == 202
    body = response.json()
    assert body["kafka_failures"] == 2
    assert body["clickhouse_failures"] == 0
    assert body["accepted"] == 0
    # Independent-sink guarantee: ClickHouse write still happened despite Kafka failing.
    assert len(fake_writer.written) == 2


def test_clickhouse_failure_does_not_block_kafka_publish(
    fake_publisher: FakeEventPublisher,
) -> None:
    failing_writer = FakeTelemetryWriter(fail_on_kinds={"log"})
    app = create_app(
        event_publisher_factory=lambda settings: fake_publisher,
        telemetry_writer_factory=lambda settings: failing_writer,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/telemetry", json=_valid_envelope(n=2), headers={"X-Ingestion-Key": VALID_KEY}
        )

    assert response.status_code == 202
    body = response.json()
    assert body["clickhouse_failures"] == 2
    assert body["accepted"] == 2
    assert len(fake_publisher.published) == 2


def test_rate_limit_returns_429_when_exceeded(
    monkeypatch: "pytest.MonkeyPatch", fake_publisher: FakeEventPublisher, fake_writer: FakeTelemetryWriter
) -> None:
    monkeypatch.setenv("RATE_LIMIT_EVENTS_PER_SECOND", "1")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1")
    get_settings.cache_clear()

    app = create_app(
        event_publisher_factory=lambda settings: fake_publisher,
        telemetry_writer_factory=lambda settings: fake_writer,
    )

    with TestClient(app) as client:
        first = client.post(
            "/v1/telemetry", json=_valid_envelope(n=1), headers={"X-Ingestion-Key": VALID_KEY}
        )
        second = client.post(
            "/v1/telemetry", json=_valid_envelope(n=1), headers={"X-Ingestion-Key": VALID_KEY}
        )

    get_settings.cache_clear()  # don't leak this override into other tests

    assert first.status_code == 202
    assert second.status_code == 429


def test_metrics_endpoint_exposes_prometheus_format(
    client: TestClient, fake_publisher: FakeEventPublisher, fake_writer: FakeTelemetryWriter
) -> None:
    client.post("/v1/telemetry", json=_valid_envelope(n=1), headers={"X-Ingestion-Key": VALID_KEY})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "events_ingested_total" in response.text
    assert "http_requests_total" in response.text
