# API reference (gateway, port 8005)

Interactive OpenAPI at `/docs`. All `/v1/workspaces/{ws}/…` routes need `Authorization: Bearer <access token>` and, for
state-changing calls, header `X-Requested-With: incident-platform`. Roles: viewer < developer < admin < owner.

| Area | Endpoints |
|---|---|
| Auth | `POST /v1/auth/{signup,login,refresh,logout,forgot-password,reset-password}`, `GET/PATCH /v1/auth/me` |
| Workspaces | `GET/POST /v1/workspaces`, `GET /{ws}`, members `GET/POST/PATCH/DELETE /{ws}/members[/{user}]`, `GET /{ws}/audit-logs` |
| Applications | `GET/POST /{ws}/applications`, `GET/DELETE /{ws}/applications/{id}`, `POST …/{id}/rotate-key` (key shown once) |
| Telemetry | `GET /{ws}/applications/{id}/telemetry/{summary,timeseries,endpoints,runtime,logs,traces,traces/{trace}}` |
| Incidents | `GET /{ws}/incidents[/{id}]`, `POST …/{id}/status`, `…/notes`, `…/analyze`, `…/hypotheses/{h}/review`, `POST /{ws}/applications/{id}/detect` |
| Deployments | `GET /{ws}/deployments`, `POST /{ws}/applications/{id}/deployments`, **`POST /v1/deployments`** (header `X-Ingestion-Key`) |
| GitHub / code | `GET /{ws}/github/status`, `POST …/github/{install-url,sync}`, `GET /{ws}/repositories[/{id}]`, `POST …/connect|disconnect|scans`, `GET /{ws}/scans/{id}`, `GET /{ws}/findings[/{id}]`, `POST …/findings/{id}/triage|explain`, `GET …/repositories/{id}/report.{csv,pdf}`; webhook `POST /v1/github/webhook` (HMAC) |
| Integrations | `GET /{ws}/integrations/status` (booleans and missing variable names only) |
| Internal | `/internal/v1/*` service-to-service (bearer `INTERNAL_API_TOKEN`); not for browsers |
| Ingestion service (port 8001) | `POST /otlp/v1/{traces,metrics,logs}` OTLP/HTTP **JSON** (protobuf not supported), header `X-Ingestion-Key` |

Errors: 401 unauthenticated, 403 role too low, 404 not found *or not your workspace*, 422 validation, 429 rate limited, 503 dependency not configured.
