# Deployment

## Local (Docker Compose)
```
cp .env.example .env          # edit secrets; never commit .env
make infra-up                 # postgres, redis, redpanda, clickhouse + services
make migrate
open http://localhost:3000
```
Compose has **not** been exercised end to end in the environment this repo was developed in (see README limitations); run
`docker compose -f infra/docker/docker-compose.yml config` and bring services up one at a time on first use.

## Required for production
`DATABASE_URL`, `AUTH_SECRET_KEY` (≥32 random chars; the gateway refuses to start with the default outside development),
`ENVIRONMENT=production`, `COOKIE_SECURE=true`, `CORS_ALLOWED_ORIGINS`, `DASHBOARD_URL`, `CLICKHOUSE_URL` (+ read-only user),
`PUBLIC_INGESTION_URL`. Dashboard: `GATEWAY_URL` (runtime). Optional: `LLM_*`, `GITHUB_*`, `SLACK_WEBHOOK_URL`, `PAGERDUTY_ROUTING_KEY`.

## Render review (`render.yaml`)
* Services: ingestion, correlation, reasoning, alert-router (existing), **api-gateway**, dashboard. All are `plan: free` web services.
* Free web services sleep when idle: the first telemetry batch after sleep can be delayed or dropped, and the gateway's detection loop
  pauses while asleep. Use a paid plan (or a pinger) for anything you rely on.
* The **scan worker needs a background worker** (not on the free plan); its block is provided commented out in `render.yaml`.
* Render Postgres is fine for the gateway. ClickHouse and Kafka are **not** provided by Render: bring ClickHouse Cloud and a Kafka-compatible
  service (the blueprint expects `sync: false` secrets for them).
* Set `GATEWAY_URL` on the dashboard to the gateway's public URL, and `CORS_ALLOWED_ORIGINS`/`DASHBOARD_URL` on the gateway to the dashboard URL.
* Run migrations (`python packages/db/src/migrate.py up`) as a pre-deploy command or one-off job; the gateway does not auto-migrate.
* The Blueprint was reviewed statically only (valid YAML, env names match `config.py`); it was not deployed from here.

## Operations
Back up Postgres; rotate ingestion keys from the dashboard; rotate `AUTH_SECRET_KEY` only with a planned logout of all sessions; keep the scan
worker isolated; set a ClickHouse TTL on `telemetry_raw` for retention.
