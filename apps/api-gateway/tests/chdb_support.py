"""
Test-only helpers: run the gateway's REAL ClickHouse SQL against chdb (the embedded ClickHouse
engine) using the REAL shared table definition. Not a substitute for a ClickHouse server
(no network, auth, or cluster behaviour), but it does execute genuine ClickHouse SQL semantics.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from chdb import session as chdb_session
from incident_schemas.clickhouse_ddl import CREATE_TABLE_SQL


class ChdbExecutor:
    def __init__(self) -> None:
        self.session = chdb_session.Session()
        self.session.query(CREATE_TABLE_SQL)
        self.queries: list[tuple[str, dict]] = []

    def query(self, sql: str, params: dict) -> list[dict]:
        self.queries.append((sql, params))
        out = str(self.session.query(sql, "JSONEachRow", params={k: str(v) for k, v in params.items()})).strip()
        return [json.loads(line) for line in out.splitlines()] if out else []

    def insert(self, rows: list[dict]) -> None:
        if rows:
            self.session.query("INSERT INTO telemetry_raw FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def span(ws, app, when, route="/api/foods", method="GET", status=200, duration=100.0, trace=None, span_id=None,
         parent="", kind=2, op=None, span_status=None, service="shop", extra=None):
    attrs = {"platform.application_id": app, "span.kind": kind, **(extra or {})}
    if kind == 2:
        attrs.update({"http.method": method, "http.status_code": status})
        if route:
            attrs["http.route"] = route
    return {
        "workspace_id": ws, "service_name": service, "kind": "trace_span", "timestamp": ts(when),
        "trace_id": trace or uuid.uuid4().hex, "span_id": span_id or uuid.uuid4().hex[:16], "parent_span_id": parent,
        "operation_name": op or f"{method} {route}", "duration_ms": duration,
        "status": span_status or ("error" if status >= 500 else "ok"), "attributes": json.dumps(attrs),
    }


def log(ws, app, when, message, severity="info", trace="", span_id="", service="shop", extra=None):
    return {"workspace_id": ws, "service_name": service, "kind": "log", "timestamp": ts(when), "severity": severity,
            "message": message, "trace_id": trace, "span_id": span_id,
            "attributes": json.dumps({"platform.application_id": app, "platform.synthetic": False, **(extra or {})})}


def metric(ws, app, when, name, value, service="shop"):
    return {"workspace_id": ws, "service_name": service, "kind": "metric", "timestamp": ts(when), "metric_name": name,
            "value": value, "attributes": json.dumps({"platform.application_id": app, "scope": "process"})}


def minutes_ago(n: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=n)
