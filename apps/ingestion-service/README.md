# Ingestion Service

The single public entrypoint for telemetry into the platform. Validates,
authenticates, rate-limits, and fans each event out to two independent sinks:

- **Kafka** (`telemetry.events` topic) - near-real-time feed for the correlation engine
- **ClickHouse** (`telemetry_raw` table) - durable, queryable store for raw telemetry

## Why two independent sinks instead of one

A Kafka outage and a ClickHouse outage are different failure modes with
different blast radii. If Kafka is down, the correlation engine goes blind in
real time - that's the more urgent failure. If ClickHouse is down, historical
querying degrades but the correlation engine (which reads from Kafka, not
ClickHouse) is unaffected. Coupling them (e.g. only publishing to Kafka after
a successful ClickHouse write) would mean a ClickHouse hiccup silently blinds
the real-time pipeline too. The `/v1/telemetry` response reports
`kafka_failures` and `clickhouse_failures` separately so callers - and
whoever's on call - can tell which one is actually broken.

## Endpoints

```
POST /v1/telemetry     Ingest a batch of telemetry events (requires X-Ingestion-Key)
GET  /healthz            Liveness check, no auth required
```

See `packages/schemas/src/incident_schemas/telemetry.py` for the exact
request schema (`TelemetryEnvelope`: a batch of `LogEvent` | `MetricEvent` |
`TraceSpanEvent`, discriminated by a `kind` field).

## Local development

```bash
# from repo root
make infra-up                                  # postgres, redpanda, redis, clickhouse
cd apps/ingestion-service
pip install -r requirements-dev.txt
pytest -v
uvicorn app.main:app --reload --port 8001
```

```bash
curl -X POST http://localhost:8001/v1/telemetry \
  -H "Content-Type: application/json" \
  -H "X-Ingestion-Key: dev-local-ingestion-key" \
  -d '{
    "idempotency_key": "batch-1",
    "events": [{
      "kind": "log",
      "workspace_id": "11111111-1111-1111-1111-111111111111",
      "service_name": "checkout-api",
      "timestamp": "2026-08-05T10:00:00Z",
      "severity": "error",
      "message": "payment gateway timeout"
    }]
  }'
```

## Testing strategy

`app/kafka_producer.py` and `app/clickhouse_writer.py` are both defined
behind small `Protocol` interfaces (`EventPublisher`, `TelemetryWriter`).
Route handlers depend on `request.app.state.event_publisher` /
`.telemetry_writer`, never on the concrete Kafka/ClickHouse classes directly.
`create_app()` accepts factory functions for both, defaulting to the real
implementations - tests pass factories that return in-memory fakes instead
(see `tests/conftest.py`), so the full FastAPI app, including its real
lifespan startup/shutdown sequence, is exercised in tests without needing a
live Kafka or ClickHouse instance. Wire-level correctness against the real
brokers is covered separately by an integration run against
`infra/docker/docker-compose.yml` in CI.

## Rate limiting

In-process token bucket, keyed per API key (`app/rate_limiter.py`). Documented
limitation: this is correct for one replica but under-enforces (by a factor
of N) across N replicas behind a load balancer. See the docstring in that
file for the exact swap-in fix (Redis-backed bucket, same interface) when
this service is horizontally scaled - deferred to keep Phase 2 focused, not
because the limitation is unknown.

## Config

All settings are environment variables, see `.env.example` at the repo root
and `app/config.py` (`Settings`) for the full list and defaults.
