# Architecture

```
 monitored app (@incident-platform/node, OTel) ──OTLP/HTTP JSON + X-Ingestion-Key──▶ ingestion-service ─▶ Kafka ─▶ ClickHouse writer
        │ registerDeployment()                                                                                       │
        ▼                                                                                                            ▼
 ┌───────────── api-gateway (FastAPI) ─────────────┐   reads telemetry  ┌──────────────┐
 │ auth · workspaces · RBAC · audit                │◀───────────────────│  ClickHouse  │
 │ detection (z-score) → incidents → evidence → RCA│                    └──────────────┘
 │ GitHub App · repositories · scans · findings    │──▶ Postgres (system of record)
 │ reports (CSV/PDF) · integrations status         │
 └───────▲───────────────────────────┬─────────────┘
         │ /gw proxy (cookies first-party)           │ scan queue (Postgres)
   Next.js dashboard                         scan-worker ──▶ scanner package (sandboxed tools) ──▶ GitHub tarballs (read-only)
```

**Boundaries**
* *Deterministic first.* Findings come from scanners; incidents from a statistical detector over measured metrics. The LLM
  only explains/hypothesises, behind one abstraction (`packages/llm`, `LLM_MODEL` + `LLM_API_KEY`), and everything works without it.
* *Tenant isolation.* Every workspace-scoped route resolves membership first (404 non-member, 403 insufficient role) and every SQL
  query filters by `workspace_id`. Ingestion keys map to exactly one application.
* *Auth.* Argon2 passwords, short-lived HS256 access token (held in memory by the dashboard), rotating opaque refresh token in an
  httpOnly cookie, CSRF header on state-changing calls, login rate limits, CORS allow-list.
* *Evidence-grounded RCA.* Evidence is bounded and redacted; model output must cite evidence ids or it is dropped (one retry);
  results are "hypothesis, not proof" and need human accept/reject/edit. Deployments are candidates, not causes.
* *Dedupe.* One open incident per (application, fingerprint) enforced by a partial unique index.
* *Untrusted code.* Repositories are read, never executed; tools run sandboxed with fixed configs.
* *Redaction.* Secrets are redacted in the SDK, at ingestion, in stored evidence and again at read time.
* *Synthetic data.* Anything seeded for demos carries `is_synthetic` and shows a DEMO badge; it is never merged into real counts silently.

**Services** `apps/api-gateway`, `apps/ingestion-service`, `apps/correlation-engine`, `apps/reasoning-service`, `apps/alert-router` (earlier
pipeline, Kafka-based), `apps/dashboard`. **Packages** `db` (migrations), `schemas`, `redaction`, `llm`, `scanner`, `node-sdk`.
The gateway's own detection path (`DETECTION_ENABLED`) is what the dashboard uses; the Kafka correlation/reasoning services are the
earlier pipeline and are not required for the dashboard flows.
