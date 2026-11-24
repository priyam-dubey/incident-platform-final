"""Detection runner: telemetry -> incident (deterministic) -> evidence -> optional LLM RCA -> notifications."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from redaction import redact

from app import telemetry_queries as q
from app.detector import RECENT_BUCKETS, Detection, detect

logger = logging.getLogger("incident-service")
WINDOW = timedelta(hours=1)


def _safe(text: str, limit: int = 400) -> str:
    return redact(text or "").text[:limit]


def build_evidence(repo, executor, workspace_id, app: dict, incident: dict, det: Detection, scope: q.Scope) -> list[dict]:
    """Bounded, redacted evidence drawn from real telemetry in the incident window. Never raw telemetry dumps."""
    recent_start = scope.end - timedelta(seconds=scope.bucket_seconds * RECENT_BUCKETS)
    s = q.Scope(scope.workspace_id, scope.application_id, recent_start - timedelta(minutes=5), scope.end)
    ev = [{"source_type": "metric", "source_ref": f"metric:{det.detector}:{scope.end.strftime('%Y%m%dT%H%M')}",
           "snippet": _safe("; ".join(f"{k}={v}" for k, v in det.details.items())), "relevance": 1.0, "occurred_at": scope.end}]
    for e in q.shape_endpoints(executor.query(*q.endpoints_query(s, "errors", 3))):
        if e["errors_5xx"]:
            ev.append({"source_type": "metric", "source_ref": f"endpoint:{e['method']} {e['route']}",
                       "snippet": _safe(f"{e['method']} {e['route']}: {e['requests']} requests, {e['errors_5xx']} 5xx, p95={e['p95_ms']} ms"),
                       "relevance": 0.9, "occurred_at": scope.end})
    for l in q.shape_logs(executor.query(*q.logs_query(s, ["error", "fatal"], None, None, 5))):
        ev.append({"source_type": "log", "source_ref": f"log:{l['timestamp']}:{(l.get('trace_id') or '')[:32]}",
                   "snippet": _safe(l["message"]), "relevance": 0.8, "occurred_at": _dt(l["timestamp"], scope.end)})
    for t in q.shape_traces(executor.query(*q.traces_query(s, only_errors=True, limit=3))):
        ev.append({"source_type": "trace", "source_ref": f"trace:{t['trace_id']}",
                   "snippet": _safe(f"trace {t['trace_id']}: {t['spans']} spans, {t['failed_spans']} failed, {t['duration_ms']} ms, root={t.get('root_operation')}"),
                   "relevance": 0.7, "occurred_at": _dt(t.get("start"), scope.end)})
    for d in repo.deployments_between(workspace_id, app["id"], incident["started_at"] - timedelta(minutes=60), incident["started_at"] + timedelta(minutes=5)):
        ev.append({"source_type": "deploy", "source_ref": f"deploy:{d['id']}",
                   "snippet": _safe(f"deployment of version={d['version']} commit={d['commit_sha']} branch={d['branch']} at {d['deployed_at'].isoformat()}"),
                   "relevance": 0.6, "occurred_at": d["deployed_at"]})
    return ev


def _dt(v, default):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return default


def detect_application(repo, executor, app: dict, now: datetime | None = None) -> list[tuple[dict, bool, q.Scope, Detection]]:
    now = now or datetime.now(timezone.utc)
    scope = q.Scope(str(app["workspace_id"]), str(app["id"]), now - WINDOW, now)
    points = q.shape_timeseries(executor.query(*q.timeseries_query(scope)), scope)["points"]
    out = []
    for det in detect(str(app["id"]), points):
        started = datetime.fromisoformat(points[-RECENT_BUCKETS]["t"])
        inc, created = repo.upsert_incident(app["workspace_id"], app, det, started)
        repo.add_evidence(inc["id"], build_evidence(repo, executor, app["workspace_id"], app, inc, det, scope))
        out.append((inc, created, scope, det))
    return out
