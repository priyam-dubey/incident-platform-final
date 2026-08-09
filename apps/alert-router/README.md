# Alert Router

Two jobs in one process:

1. **HTTP review API** — the dashboard's only path for reading incidents and
   submitting human verdicts (`accepted` / `rejected` / `edited`) on AI
   hypotheses.
2. **Real-time escalation** — consumes `incident.candidates` from Kafka and
   immediately pages Slack/PagerDuty for high/critical incidents, independent
   of when (or whether) a human opens the dashboard.

## Endpoints

```
GET  /v1/incidents?workspace_id=...&status_filter=...   list incidents
GET  /v1/incidents/{id}                                   incident + evidence + hypotheses
POST /v1/hypotheses/{id}/verdict                            {"verdict": "accepted"|"rejected"|"edited", "notes": "..."}
GET  /healthz
```

All `/v1/*` routes require `X-API-Key`. `POST .../verdict` additionally
requires `X-Reviewer-Email` to attribute the verdict to a human - the
dashboard's backend is the one trusted to set this correctly (see the
docstring in `app/auth.py` for the documented limitation: this is a trusted
header, not an end-to-end verified identity, and is called out as a Phase 7+
hardening item rather than glossed over).

## Why verdicts matter beyond "mark it reviewed"

`app/verdict_service.py` is the one place a human's judgment turns into two
things simultaneously: an `eval_examples` row (feeding the offline
evaluation harness that scores future prompt/model changes) and an incident
status transition (`published` on accept/edit, `dismissed` once every
hypothesis for an incident has been rejected). Every verdict submitted
through this API produces both - there's no way to update review state
without also contributing to the eval dataset.

## Escalation design

`app/escalation_policy.py` decides *which* channels get paged (pure
function of severity - critical pages PagerDuty + Slack, high pages Slack
only, medium/low never interrupt anyone). `app/alert_dispatcher.py` decides
*how reliably* those channels get reached: each channel is retried up to
`ALERT_MAX_ATTEMPTS` times with exponential backoff, independently of every
other channel (a failing Slack webhook never delays a working PagerDuty
call), and every attempt - success or final failure - is written to
`alert_events` as an audit trail.

## Local development

```bash
# from repo root
make infra-up
cd apps/alert-router
pip install -r requirements-dev.txt
pytest -v
uvicorn app.main:app --reload --port 8004
```

## Testing strategy

Same Protocol + factory-injection pattern as the other services.
`IncidentRepository` is a Protocol (`PostgresIncidentRepository` real,
`FakeIncidentRepository` for tests); `create_app(repository_factory=...,
enable_escalation_consumer=False)` lets route tests run the real FastAPI
lifespan without dialing Kafka or Postgres. The dispatcher's retry/backoff
and concurrency behavior is tested directly against fake senders with real
(short) timing, including a test that asserts channels are dispatched
concurrently rather than sequentially.
