# Correlation Engine

Consumes raw telemetry from Kafka (`telemetry.events`), performs deterministic
anomaly detection and cross-service clustering, and emits `IncidentCandidate`
objects - the bounded, schema-validated evidence structure the reasoning
service (Phase 4) is allowed to reason over. This is the enforcement point
for the platform's core rule: **the AI never sees raw telemetry.**

## Pipeline

```
Kafka telemetry.events
        │
        ▼
 dispatch by event kind (log / metric / trace_span)
        │
   ┌────┼────────────────┐
   ▼    ▼                ▼
 metric  log/trace     (both feed into...)
   │        │
   ▼        ▼
AnomalyDetector   EvidenceBuffer
(rolling z-score  (bounded per-service
 per service+metric)  ring buffer)
   │                    │
   └─────────┬──────────┘
             ▼  every `correlation_window_seconds` (tick)
        ClusterEngine
   (union-find: groups anomalies by
    temporal proximity + shared trace_id)
             │
             ▼
     build_incident_candidate()
   (attaches buffered evidence,
    derives severity, validates
    against the shared schema)
             │
             ▼
  PostgresAndKafkaIncidentSink
  (persists to `incidents` + `incident_evidence`,
   publishes to Kafka `incident.candidates`)
```

## Design choices worth knowing

- **Tick-based, not per-event emission.** A cluster is built once per
  `correlation_window_seconds` from everything anomalous in that window,
  rather than emitting (and re-emitting, and re-emitting) a growing cluster
  as each new service's anomaly arrives. See `app/pipeline.py` docstring.
- **Union-find clustering**, not pairwise O(n^2) comparison - matters once a
  single wide-blast-radius incident produces hundreds of anomalies in one
  window. See `app/cluster_engine.py`.
- **Z-score baseline excludes the value being scored** - a value can never
  pull its own baseline toward itself, or a sustained spike would gradually
  become "normal" mid-spike and stop triggering. See `app/anomaly_detector.py`.
- **Evidence fallback**: if an anomaly cluster has no buffered log/trace
  evidence (a metric-only anomaly with nothing correlated), the pipeline
  synthesizes a minimal evidence item describing the anomaly itself, rather
  than silently dropping a real incident candidate because the schema
  requires at least one evidence item. See `app/candidate_builder.py`.

## Local development

```bash
# from repo root
make infra-up
cd apps/correlation-engine
pip install -r requirements-dev.txt
pytest -v
uvicorn app.main:app --reload --port 8002
```

## Testing strategy

Same Protocol-based fake-injection pattern as the ingestion service.
`ServiceRegistry` and `IncidentCandidateSink` are Protocols; production uses
`PostgresServiceRegistry` / `PostgresAndKafkaIncidentSink`, tests use
in-memory fakes (`tests/conftest.py`). The anomaly detector, cluster engine,
and candidate builder are pure logic with zero infra dependencies and are
tested directly - 28 of this service's tests require no fakes at all.

## Operational endpoints

```
GET /healthz   liveness check
GET /stats     running counters: events_consumed, ticks_run, candidates_emitted
```
