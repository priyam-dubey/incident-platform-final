# AI-Native Observability & Incident Intelligence Platform

**Author:** Priyambad Dubey ([priyambaddubey2004@gmail.com](mailto:priyambaddubey2004@gmail.com))

A system that watches everything happening across a company's servers, notices when something looks wrong, and tries to explain *why* — automatically — before a human even opens their laptop.

It combines deterministic telemetry correlation (real statistics, no AI) with constrained AI reasoning (an LLM that is never allowed to hallucinate a root cause) to detect, explain, and document production incidents.

> 🟡 **Status:** Actively being wired up for a live deployment (free tier) in the next few days. Until then, run it locally — instructions below.

---

## What this can actually help with

- **On-call engineers** who are tired of opening five dashboards to figure out why something broke.
- **Small teams without a dedicated SRE org** who want incident intelligence without buying an enterprise observability platform.
- **Anyone learning how production AI systems are built properly** — this repo is a real, working reference for patterns like citation-grounded LLM output, event-driven microservices, and human-in-the-loop review, not a toy demo.
- **Contributors who want to practice building real infra** — Kafka, ClickHouse, Postgres, LangGraph, and a proper Next.js frontend, all wired together and tested.

---

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
 Reasoning Service (LangGraph + LLM, schema-constrained structured output)
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

**The one rule every phase enforces: the model never sees raw telemetry.** Only the correlation engine's bounded, redacted `IncidentCandidate` evidence ever reaches the reasoning service, and every claim the model makes is programmatically checked against that evidence before a human ever sees it. If a claim can't be backed up, it gets retried once, and if it still can't be grounded, it's dropped rather than shown as fact.

---

## Repo layout

```
incident-platform/
├── apps/
│   ├── ingestion-service/     # telemetry intake, Kafka+ClickHouse fan-out
│   ├── correlation-engine/    # anomaly detection, clustering, redaction
│   ├── reasoning-service/     # LangGraph reasoning, citation validation
│   ├── alert-router/          # escalation, human review API
│   └── dashboard/             # Next.js frontend
├── packages/
│   ├── db/                    # SQL schema + migrations (shared source of truth)
│   ├── schemas/                # Shared Pydantic contracts for cross-service data
│   └── redaction/               # PII/secret scrubbing, used by correlation-engine
├── infra/
│   └── docker/                 # docker-compose stack: postgres, redpanda, redis, clickhouse, all 5 apps
├── render.yaml                 # deployment config for Render's free tier
└── .github/workflows/          # CI - one job per package/app, all independently testable
```

---

## Tech stack

| Layer | Tech |
|---|---|
| Ingestion / Correlation / Reasoning / Alerts | Python, FastAPI, Pydantic |
| AI orchestration | LangGraph, LLM API (schema-constrained structured output) |
| Event bus | Kafka-compatible (Redpanda) |
| Telemetry storage | ClickHouse |
| System of record | PostgreSQL |
| Cache / rate limiting | Redis |
| Frontend | Next.js, TypeScript, Tailwind |
| Observability | Prometheus metrics, structured JSON logging |
| Testing | pytest, TypeScript `tsc` + `next build` |

---

## Running it locally

Requires Docker + Docker Compose, Python 3.12+, Node 20+.

```bash
git clone https://github.com/priyam-dubey/incident-platform-final.git
cd incident-platform-final
cp .env.example .env        # fill in your LLM API key before starting the reasoning service
make infra-up                # postgres, redpanda, redis, clickhouse, and all 5 application services
make migrate                   # apply DB schema
make test-all                    # run every Python service's test suite
```

Or run a single service against the infra stack without rebuilding its container:

```bash
make infra-up
cd apps/ingestion-service && pip install -r requirements-dev.txt && pytest -v
make run-ingestion
```

For the dashboard:

```bash
cd apps/dashboard
cp .env.local.example .env.local
npm install
npm run dev
```

Then open **http://localhost:3000**.

**On Windows?** Use WSL2 — Docker Desktop already runs on it, and every command above works unmodified inside a WSL Ubuntu terminal. Native PowerShell works too, but `make` isn't available by default; run the underlying `docker compose` / `pytest` / `uvicorn` commands directly instead (see each service's own README).

---

## How to test it

**Automated tests (what actually proves the code works):**

```bash
make test-all
```

This runs the full test suite across every Python service — anomaly detection math, citation validation logic, retry-on-hallucination behavior, verdict/escalation workflows, redaction correctness — no Docker or live API key required. 127 tests, all real, all passing.

For the dashboard:

```bash
cd apps/dashboard
npm install
npx tsc --noEmit
npm run build
```

**Manually poking at a running instance:**

```bash
# health checks
curl http://localhost:8001/healthz   # ingestion
curl http://localhost:8002/healthz   # correlation
curl http://localhost:8003/healthz   # reasoning
curl http://localhost:8004/healthz   # alert router

# send a fake error spike and watch it get picked up
curl -X POST http://localhost:8001/v1/telemetry \
  -H "Content-Type: application/json" \
  -H "X-Ingestion-Key: dev-local-ingestion-key" \
  -d '{
    "idempotency_key": "test-batch-1",
    "events": [{
      "kind": "metric",
      "workspace_id": "11111111-1111-1111-1111-111111111111",
      "service_name": "checkout-api",
      "timestamp": "2026-01-01T10:00:00Z",
      "metric_name": "error_rate",
      "value": 0.9
    }]
  }'
```

Send enough of these (varying the value) to build a baseline, then send an obvious spike — within one correlation window, an incident candidate should appear in Postgres and get picked up by the reasoning service.

## How a user will test it from the live site (once deployed)

Once the free-tier deployment is live, the loop will be:

1. Open the dashboard URL and enter the demo workspace ID (shown on the homepage).
2. Browse the incident feed — pre-seeded demo incidents will be there to look at without needing to send your own telemetry.
3. Click into an incident to see the evidence trail and the AI's root-cause hypothesis, with clickable citation numbers linking straight to the evidence backing each claim.
4. Try Accept / Reject / Edit on a hypothesis and watch the incident status change.

The live URL and demo workspace ID will be added here as soon as deployment is confirmed working.

---

## Contributing — PRs welcome!

This is open source and genuinely open to contributions, big or small. Ways to help:

- Try running it locally and open an issue for anything that breaks or is unclear.
- Pick up anything in **Future Scope** below.
- Improve test coverage, docs, or the dashboard's UI/UX.
- Add a new anomaly-detection strategy, a new alert channel, or a new evidence source type.

**To contribute:**

```bash
# 1. Fork the repo, then:
git clone https://github.com/<your-username>/incident-platform-final.git
cd incident-platform-final
git checkout -b your-feature-name

# 2. Make your changes, run tests
make test-all

# 3. Commit, push, and open a PR
git push origin your-feature-name
```

Keep PRs focused (one thing at a time), add/update tests for anything you change, and explain the *why* in your PR description, not just the *what*. No formal CLA — just be reasonable and this'll be fast to review.

Found a bug, have an idea, or just want to say hi? Open an issue or email priyambaddubey2004@gmail.com.

---

## Future scope

- [ ] **Live deployment on Render's free tier** — `render.yaml` is already in the repo, deployment in progress.
- [ ] **Real authentication** — the dashboard currently has no login/session system; this is the top hardening priority before any real usage.
- [ ] **Query-level multi-tenant isolation** — workspace_id exists on every table, but nothing yet stops an authenticated caller from requesting another workspace's data by ID.
- [ ] **Offline evaluation harness** — every human accept/reject/edit is already saved as labeled data (`eval_examples`); the next step is a proper harness that replays this against prompt/model changes to catch regressions before they ship.
- [ ] **Fine-tuned re-ranking / embeddings** for evidence relevance scoring.
- [ ] **More alert channels** beyond Slack/PagerDuty (Discord, email, Teams).
- [ ] **A public demo mode** with pre-seeded synthetic incidents so anyone can explore the dashboard without standing up the full stack.
- [ ] **Kubernetes manifests** for a real production deployment beyond Docker Compose.
- [ ] **Cost/latency dashboards** for LLM usage (tokens, cost-per-incident, retry rate).

---

## Honest current limitations

This was built and tested piece-by-piece (127 passing tests, a real `next build`, real SQL syntax checks) but has **not yet been run as a full live stack end-to-end** — that's what the upcoming deployment will confirm. Known gaps right now:

- No dashboard authentication.
- No live LLM call has been verified yet in the deployed environment (works in tests against a mocked client).
- No live Slack/PagerDuty delivery confirmed yet.

These are listed here on purpose, not hidden — if you hit one of them, that's expected, not a mystery bug.

---

## License

Open source. (Add your preferred license here — e.g. MIT — if not already present in the repo.)

## Maintainer

**Priyambad Dubey**
📧 priyambaddubey2004@gmail.com
🔗 [github.com/priyam-dubey](https://github.com/priyam-dubey)
