# AI-Native Observability & Incident Intelligence Platform

Production-grade platform that combines deterministic telemetry correlation with
constrained AI reasoning to identify, explain, and document production incidents
— without hallucinating root causes.

## Architecture

```
Telemetry (logs/metrics/traces)
        │  OTel-style ingestion, authenticated + rate-limited
        ▼
 Ingestion Service (FastAPI)  ──────►  ClickHouse (raw telemetry, durable record)
        │
        ▼  Kafka/Redpanda topic: telemetry.events
        │
 Correlation Engine (FastAPI + consumer worker)
        │  rolling z-score anomaly detection (per service+metric)
        │  union-find clustering (temporal proximity + shared trace ids)
        │  PII/secret redaction applied to buffered evidence
        ▼
 "Incident Candidate" (bounded, schema-validated evidence object)
        │
        ▼  Kafka topic: incident.candidates
        │
 Reasoning Service (LangGraph + Gemini SDK, schema-constrained structured output)
        │  hypothesis generation → citation validation → retry-once-on-hallucination
        ▼
 Alert Router
        │  immediate Slack/PagerDuty escalation for high/critical severity
        │  HTTP review API: accept / reject / edit
        ▼
 Dashboard (Next.js) ──── human verdict ────► eval_examples (feeds future eval harness)
        │
        ▼
 Published Incident + Postmortem
```

The one rule every phase enforces: **the model never sees raw telemetry.**
Only the correlation engine's bounded, redacted `IncidentCandidate` evidence
ever reaches the reasoning service, and every claim the model makes is
programmatically checked against that evidence before a human ever sees it.

## Repo layout

```
incident-platform/
├── apps/
│   ├── ingestion-service/     # Phase 2 - telemetry intake, Kafka+ClickHouse fan-out
│   ├── correlation-engine/    # Phase 3 - anomaly detection, clustering, redaction
│   ├── reasoning-service/     # Phase 4 - LangGraph reasoning, citation validation
│   ├── alert-router/          # Phase 5 - escalation, human review API
│   └── dashboard/             # Phase 6 - Next.js frontend
├── packages/
│   ├── db/                    # SQL schema + migrations (shared source of truth)
│   ├── schemas/                # Shared Pydantic contracts for cross-service data
│   └── redaction/               # Phase 7 - PII/secret scrubbing, used by correlation-engine
├── infra/
│   └── docker/                 # docker-compose stack: postgres, redpanda, redis, clickhouse, all 5 apps
└── .github/workflows/          # CI - one job per package/app, all independently testable
```

## Local development

Requires Docker + Docker Compose, Python 3.12+, Node 20+.

```bash
cp .env.example .env
make infra-up          # postgres, redpanda, redis, clickhouse, and all 5 application services
make migrate            # apply DB schema
make test-all             # run every Python service's test suite
```

Or run a single service against the infra stack without rebuilding its container:

```bash
make infra-up
cd apps/ingestion-service && pip install -r requirements-dev.txt && pytest -v
make run-ingestion
```

See each service's own README for details specific to it.

## Testing philosophy, consistently applied across every service

Every service that talks to real infrastructure (Postgres, Kafka, ClickHouse,
Slack/PagerDuty, the Gemini API) defines that dependency behind a small
`Protocol` interface. Production code gets the real implementation; tests get
an in-memory fake implementing the same interface, injected through a
`create_app(..._factory=...)` pattern so the *actual* FastAPI lifespan runs in
tests — not a bypassed one. This caught two real bugs during development
(documented in the relevant service READMEs): a `TestClient` that would have
dialed live Kafka/ClickHouse in ingestion-service and alert-router before the
factory pattern was introduced. Pure logic (anomaly detection, clustering,
citation validation, redaction, escalation policy) is tested directly, with
zero infrastructure involved at all.

Total test count across the platform's Python services: **127 tests**, all
passing, all real (no skipped/xfail placeholders), runnable with
`make test-all` without Docker. The dashboard (TypeScript) is verified via
`tsc --noEmit` and a real `next build` rather than a unit-test count.

## Observability

Every Python service exposes `/healthz` and `/metrics` (Prometheus format).
Structured JSON logging throughout (`app/logging_config.py`, identical pattern
in every service) so logs are queryable without a regex parser in front of
them. Domain-specific counters, not just HTTP metrics — e.g.
`events_publish_failures_total{sink="kafka"}` in ingestion,
`hypotheses_rejected_total` in the reasoning service (a rising hallucination
rate is the earliest signal a prompt/model change degraded citation grounding,
well before human review data would catch it), `verdicts_submitted_total` in
the alert router.

## Security posture, stated plainly rather than glossed over

- **Machine-to-machine auth**: constant-time API key checks (ingestion, alert
  router). Documented as sufficient for this stage, not as a finished
  security story.
- **Human auth**: does not exist yet. The dashboard has no session/login
  layer — see `apps/dashboard/README.md` for exactly what's cut and why it's
  called out explicitly instead of faked.
- **PII/secrets**: redacted (`packages/redaction`) before telemetry evidence
  is buffered for the reasoning service or shown to a human — not after.
- **Multi-tenant isolation**: enforced at the schema level
  (`workspace_id` on every table) but not yet at the query-authorization
  level (nothing currently stops an authenticated caller from requesting a
  different workspace's data by id) — the next real hardening step before
  this could take multiple customers.

## Phase history

- [x] **Phase 1** — Monorepo scaffold, infra stack, DB schema/migrations, shared schemas
- [x] **Phase 2** — Ingestion service (telemetry intake, Kafka + ClickHouse fan-out, auth, rate limiting, Prometheus metrics)
- [x] **Phase 3** — Correlation engine (anomaly detection, cross-service clustering, incident candidates, Prometheus metrics)
- [x] **Phase 4** — Reasoning service (LangGraph, tool-forced structured output, citation validation, retry-on-hallucination, Prometheus metrics)
- [x] **Phase 5** — Alert router / human review (escalation dispatcher with retry/backoff, verdict API, eval-dataset feed, Prometheus metrics)
- [x] **Phase 6** — Dashboard (Next.js, evidence-linked confidence readouts, verdict controls)
- [x] **Phase 7** — Redaction (PII/secrets scrubbed before evidence buffering), Prometheus observability across all services, documented security posture

Each phase was built fully functional, tested, and documented before the next began.

## What's honestly still missing for a real production deployment

This was built end-to-end in a sandboxed environment without a live Docker
daemon, live cloud infrastructure, or a Gemini API key to call. Every
piece of logic that could be verified without those things was — real
`pytest` runs, a real `npm run build`, real SQL linting against Postgres
syntax. What was **not** verified end-to-end: an actual `docker compose up`
of the full stack, a live LLM call against `root_cause_v1`'s prompt, and a
live Slack/PagerDuty webhook delivery. These are the concrete next steps
before calling this deployed rather than built.
