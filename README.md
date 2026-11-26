# Incident Platform — code intelligence + runtime monitoring + evidence-grounded RCA

**Author:** Priyambad Dubey ([priyambaddubey2004@gmail.com](mailto:priyambaddubey2004@gmail.com))

A multi-tenant platform that (1) scans your GitHub repositories with deterministic security/quality tools, (2) monitors running
Node.js/Express apps through OpenTelemetry, (3) detects incidents statistically and (4) proposes **evidence-cited, human-reviewed**
root-cause hypotheses. An LLM (default `gemini/gemini-2.5-flash`) only explains; every finding and incident exists without it.

> Deployments, commits and AI output are **hypotheses, not proofs**. Integrations that are not configured say "Not configured".
> Demo data is always labelled DEMO and is never mixed with real data.

## What works (verified here) and what is not
| Area | State |
|---|---|
| Auth, workspaces, RBAC (owner/admin/developer/viewer), audit log, tenant isolation | Tested on real Postgres |
| Per-app hashed, rotatable ingestion keys; OTLP/HTTP **JSON** ingestion | Tested (ingestion service + SDK + e2e) |
| Metrics/logs/traces queries, process metrics kept separate from host metrics | SQL semantics tested with embedded chdb |
| Detection (z-score on error rate & p95), dedupe, evidence, RCA retry/validation, review flow | Tested with a fake LLM |
| GitHub App install/webhooks/repos/scans | Tested against a **mocked** GitHub API only |
| Scanners (Semgrep, Bandit, Ruff, ESLint, tsc, Gitleaks) | Run for real on a deliberately vulnerable fixture; npm-audit, pip-audit, Trivy parsers tested on documented-format fixtures only (Trivy binary not run here) |
| Dashboard (Next.js) | Type-checked, production-built, 24 Playwright checks against the real gateway |
| Slack / PagerDuty / real Gemini | **Not verified** (no credentials); code paths tested with doubles |
| Docker Compose / Render / real ClickHouse + Kafka | **Not run** here; configs reviewed statically |

## Quick start (local)
```bash
cp .env.example .env                       # fill in values; never commit .env
make infra-up && make migrate              # Postgres, ClickHouse, Kafka-compatible bus, services
open http://localhost:3000                 # sign up → create an application → copy the one-time key
```
Instrument a Node app: `docs/guides/nodejs-onboarding.md`. Connect GitHub: `docs/guides/github-app-setup.md`.
AI (optional): `docs/guides/gemini-setup.md` (`LLM_MODEL`, `LLM_API_KEY` — environment only).

## Tests
```bash
make test-all          # Python packages and services
make test-gateway      # gateway on real Postgres (set TEST_DATABASE_URL)
make test-scanner      # scanner package (tools not installed report "unavailable")
make test-node-sdk     # SDK
make test-e2e          # gateway + ingestion + instrumented sample app
make test-ui-e2e       # Playwright browser e2e (needs playwright, chdb, a Next build)
```
Last full run in the build environment: schemas 16, db 8, redaction 17, llm 26, scanner 15, ingestion 42, correlation 30,
reasoning 12, alert-router 27, **gateway 94**, e2e 10, Node SDK 12, UI e2e 24 — all passing, none skipped; dashboard `tsc` clean.

## Docs
`docs/architecture.md` · `docs/api.md` · `docs/deployment.md` (incl. Render review) · `docs/guides/` (GitHub App, AI provider, code scanning, Node onboarding)

## Repo layout
`apps/api-gateway` (API + scan worker) · `apps/dashboard` (Next.js) · `apps/ingestion-service` · `apps/correlation-engine`, `reasoning-service`,
`alert-router` (earlier Kafka pipeline) · `packages/{db,schemas,redaction,llm,scanner,node-sdk}` · `infra/docker` · `tests/e2e` · `examples`

## Known limitations
* No email delivery: password-reset tokens are not sent; no invitations or email verification.
* OTLP **protobuf** is not supported (JSON only); auto-instrumentation covers http, express, mongodb. The SDK is not yet published to npm.
* The ClickHouse writer drops its in-memory buffer if a flush fails.
* Legacy `alert-router` incident routes have no workspace checks (internal API; the dashboard uses the gateway APIs instead).
* Detection is a statistical heuristic with traffic floors; it will miss slow regressions and can be noisy on low traffic.
* Free-tier hosting sleeps when idle; the scan worker needs a paid background worker.
* A real end-to-end run against the owner's MERN app (Apna Swad), a real GitHub App and a real Gemini key is still to be done.

## Contributing
Fork, branch, add tests for what you change, open a PR explaining the *why*.

## License
Open source. (Add your preferred license, e.g. MIT.)

## Maintainer
**Priyambad Dubey** · priyambaddubey2004@gmail.com · [github.com/priyam-dubey](https://github.com/priyam-dubey)
