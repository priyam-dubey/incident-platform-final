"""
Tenant-scoped telemetry queries (ClickHouse SQL). Pure functions: build (sql, params) and shape rows.

Isolation rules enforced here, not in callers:
  * EVERY query filters on workspace_id AND application_id through bound parameters.
  * Nothing user-supplied is ever interpolated into SQL text. Sort keys and metric names are
    chosen from fixed whitelists; search text, trace IDs and severities are bound parameters.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from redaction import redact

from incident_schemas.clickhouse_ddl import TELEMETRY_TABLE as T

# A "request" is an HTTP SERVER span (span_kind 2) that carries a response status.
REQUEST = "kind = 'trace_span' AND span_kind = 2 AND http_status > 0"
RUNTIME_METRICS = (
    "process.memory.usage", "nodejs.heap.used", "nodejs.heap.total",
    "nodejs.eventloop.lag.p99", "process.cpu.utilization", "process.uptime",
)
_METRIC_LIST = ", ".join(f"'{m}'" for m in RUNTIME_METRICS)  # constants, never user input
ENDPOINT_SORTS = {"requests": "requests DESC", "p95": "p95_ms DESC", "errors": "errors DESC", "avg": "avg_ms DESC"}
BUCKETS = (10, 30, 60, 300, 900, 1800, 3600, 10800, 21600, 86400)
MAX_RANGE = timedelta(days=7)
PRESETS = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080}
HIDDEN_ATTR_PREFIX = "platform."


@dataclass(frozen=True)
class Scope:
    workspace_id: str
    application_id: str
    start: datetime
    end: datetime

    @property
    def bucket_seconds(self) -> int:
        span = (self.end - self.start).total_seconds()
        for b in BUCKETS:
            if span / b <= 90:
                return b
        return BUCKETS[-1]


def resolve_range(range_: str | None, start: datetime | None, end: datetime | None, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("Provide both 'from' and 'to'")
        start, end = _utc(start), _utc(end)
    else:
        minutes = PRESETS.get(range_ or "1h")
        if minutes is None:
            raise ValueError(f"range must be one of {', '.join(PRESETS)}")
        start, end = now - timedelta(minutes=minutes), now
    if end <= start:
        raise ValueError("'to' must be after 'from'")
    if end - start > MAX_RANGE:
        raise ValueError("Time range cannot exceed 7 days")
    return start, end


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _ts(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


_SCOPE = ("workspace_id = {ws:UUID} AND application_id = {app:String} "
          "AND timestamp >= {t0:DateTime64(3,'UTC')} AND timestamp < {t1:DateTime64(3,'UTC')}")


def _params(s: Scope, **extra: Any) -> dict:
    return {"ws": s.workspace_id, "app": s.application_id, "t0": _ts(s.start), "t1": _ts(s.end), **extra}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) or math.isinf(f) else f


# ------------------------------------------------------------------ summary
def summary_query(s: Scope) -> tuple[str, dict]:
    return (
        f"SELECT count() AS requests, countIf(http_status >= 500) AS errors_5xx, "
        f"countIf(http_status >= 400 AND http_status < 500) AS errors_4xx, avg(duration_ms) AS avg_ms, "
        f"quantile(0.5)(duration_ms) AS p50_ms, quantile(0.95)(duration_ms) AS p95_ms, "
        f"quantile(0.99)(duration_ms) AS p99_ms FROM {T} WHERE {REQUEST} AND {_SCOPE}",
        _params(s),
    )


def shape_summary(rows: list[dict], s: Scope) -> dict:
    r = rows[0] if rows else {}
    n = int(r.get("requests") or 0)
    minutes = max((s.end - s.start).total_seconds() / 60.0, 1e-9)
    e5 = int(r.get("errors_5xx") or 0)
    return {
        "requests": n, "errors_5xx": e5, "errors_4xx": int(r.get("errors_4xx") or 0),
        "error_rate": (e5 / n) if n else None, "requests_per_minute": (n / minutes) if n else 0.0,
        "avg_ms": _num(r.get("avg_ms")) if n else None, "p50_ms": _num(r.get("p50_ms")) if n else None,
        "p95_ms": _num(r.get("p95_ms")) if n else None, "p99_ms": _num(r.get("p99_ms")) if n else None,
    }


# --------------------------------------------------------------- timeseries
def timeseries_query(s: Scope) -> tuple[str, dict]:
    return (
        f"SELECT toStartOfInterval(timestamp, INTERVAL {{b:UInt32}} SECOND) AS bucket, count() AS requests, "
        f"countIf(http_status >= 500) AS errors_5xx, avg(duration_ms) AS avg_ms, quantile(0.5)(duration_ms) AS p50_ms, "
        f"quantile(0.95)(duration_ms) AS p95_ms, quantile(0.99)(duration_ms) AS p99_ms "
        f"FROM {T} WHERE {REQUEST} AND {_SCOPE} GROUP BY bucket ORDER BY bucket",
        _params(s, b=s.bucket_seconds),
    )


def _bucket_start(d: datetime, b: int) -> datetime:
    return datetime.fromtimestamp(int(d.timestamp()) // b * b, tz=timezone.utc)


def fill_buckets(rows: list[dict], s: Scope, value_keys: dict[str, Any]) -> list[dict]:
    """Return a continuous series. Missing buckets get counts of 0 and None for latencies/values
    (no data is not 0 ms)."""
    b = s.bucket_seconds
    by_ts = {}
    for r in rows:
        ts = r["bucket"]
        ts = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        by_ts[_utc(ts).timestamp()] = r
    out, t = [], _bucket_start(s.start, b)
    while t < s.end:
        row = by_ts.get(t.timestamp())
        point = {"t": t.isoformat()}
        for key, default in value_keys.items():
            point[key] = (row.get(key) if row else None) if default is None else int((row or {}).get(key) or 0)
            if default is None and point[key] is not None:
                point[key] = _num(point[key])
        out.append(point)
        t += timedelta(seconds=b)
    return out


def shape_timeseries(rows: list[dict], s: Scope) -> dict:
    series = fill_buckets(rows, s, {"requests": 0, "errors_5xx": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "p99_ms": None})
    for p in series:
        p["error_rate"] = (p["errors_5xx"] / p["requests"]) if p["requests"] else None
        p["requests_per_minute"] = p["requests"] / (s.bucket_seconds / 60.0)
    return {"bucket_seconds": s.bucket_seconds, "points": series}


# ------------------------------------------------------- status distribution
def status_query(s: Scope) -> tuple[str, dict]:
    return (
        f"SELECT countIf(http_status < 200) AS c1xx, countIf(http_status >= 200 AND http_status < 300) AS c2xx, "
        f"countIf(http_status >= 300 AND http_status < 400) AS c3xx, countIf(http_status >= 400 AND http_status < 500) AS c4xx, "
        f"countIf(http_status >= 500) AS c5xx FROM {T} WHERE {REQUEST} AND {_SCOPE}",
        _params(s),
    )


def shape_status(rows: list[dict]) -> dict:
    r = rows[0] if rows else {}
    return {k: int(r.get(f"c{k}") or 0) for k in ("1xx", "2xx", "3xx", "4xx", "5xx")}


# ----------------------------------------------------------------- endpoints
def endpoints_query(s: Scope, sort: str = "requests", limit: int = 50) -> tuple[str, dict]:
    order = ENDPOINT_SORTS.get(sort)
    if order is None:
        raise ValueError(f"sort must be one of {', '.join(ENDPOINT_SORTS)}")
    return (
        f"SELECT http_method AS method, if(http_route = '', '(unrouted)', http_route) AS route, count() AS requests, "
        f"countIf(http_status >= 500) AS errors, countIf(http_status >= 400 AND http_status < 500) AS errors_4xx, "
        f"avg(duration_ms) AS avg_ms, quantile(0.95)(duration_ms) AS p95_ms, quantile(0.99)(duration_ms) AS p99_ms "
        f"FROM {T} WHERE {REQUEST} AND {_SCOPE} GROUP BY method, route ORDER BY {order}, route LIMIT {{lim:UInt32}}",
        _params(s, lim=max(1, min(limit, 200))),
    )


def shape_endpoints(rows: list[dict]) -> list[dict]:
    return [{
        "method": r["method"], "route": r["route"], "requests": int(r["requests"]), "errors_5xx": int(r["errors"]),
        "errors_4xx": int(r["errors_4xx"]), "error_rate": (int(r["errors"]) / int(r["requests"])) if int(r["requests"]) else None,
        "avg_ms": _num(r["avg_ms"]), "p95_ms": _num(r["p95_ms"]), "p99_ms": _num(r["p99_ms"]),
    } for r in rows]


# ------------------------------------------------------------ runtime metrics
def runtime_query(s: Scope) -> tuple[str, dict]:
    return (
        f"SELECT toStartOfInterval(timestamp, INTERVAL {{b:UInt32}} SECOND) AS bucket, metric_name, "
        f"avg(value) AS avg_v, max(value) AS max_v FROM {T} WHERE kind = 'metric' AND metric_name IN ({_METRIC_LIST}) "
        f"AND {_SCOPE} GROUP BY bucket, metric_name ORDER BY bucket",
        _params(s, b=s.bucket_seconds),
    )


def shape_runtime(rows: list[dict], s: Scope) -> dict:
    out = {"scope": "process", "bucket_seconds": s.bucket_seconds, "series": {}}
    for name in RUNTIME_METRICS:
        mine = [{"bucket": r["bucket"], "avg": r["avg_v"], "max": r["max_v"]} for r in rows if r["metric_name"] == name]
        pts = fill_buckets(mine, s, {"avg": None, "max": None}) if mine else []
        out["series"][name] = pts
    return out


# ----------------------------------------------------------------------- logs
SEVERITIES = ("trace", "debug", "info", "warn", "error", "fatal")


def logs_query(s: Scope, severities: list[str] | None, search: str | None, trace_id: str | None,
               limit: int = 100, offset: int = 0) -> tuple[str, dict]:
    where, extra = [f"kind = 'log'", _SCOPE], {}
    if severities:
        bad = [v for v in severities if v not in SEVERITIES]
        if bad:
            raise ValueError(f"severity must be among {', '.join(SEVERITIES)}")
        names = []
        for i, v in enumerate(severities):
            extra[f"sev{i}"] = v
            names.append(f"{{sev{i}:String}}")
        where.append(f"severity IN ({', '.join(names)})")
    if search:
        where.append("positionCaseInsensitive(message, {q:String}) > 0")
        extra["q"] = search[:200]
    if trace_id:
        where.append("trace_id = {trace:String}")
        extra["trace"] = trace_id[:64]
    return (
        f"SELECT timestamp, severity, message, trace_id, span_id, attributes FROM {T} WHERE {' AND '.join(where)} "
        f"ORDER BY timestamp DESC LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}",
        _params(s, lim=max(1, min(limit, 500)), off=max(0, offset), **extra),
    )


def public_attrs(raw: str | None) -> dict:
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in d.items() if not k.startswith(HIDDEN_ATTR_PREFIX)} if isinstance(d, dict) else {}


def shape_logs(rows: list[dict]) -> list[dict]:
    return [{
        "timestamp": _iso(r["timestamp"]), "severity": r["severity"], "message": redact(r["message"] or "").text[:8000],  # read-time redaction: defence in depth
       
        "trace_id": r["trace_id"] or None, "span_id": r["span_id"] or None, "attributes": public_attrs(r.get("attributes")),
    } for r in rows]


def _iso(v: Any) -> str:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return v
    return _utc(v).isoformat() if isinstance(v, datetime) else str(v)


# --------------------------------------------------------------------- traces
def traces_query(s: Scope, only_errors: bool = False, min_duration_ms: float | None = None, limit: int = 50) -> tuple[str, dict]:
    having, extra = [], {}
    if only_errors:
        having.append("failed_spans > 0")
    if min_duration_ms is not None:
        having.append("duration_ms >= {mind:Float64}")
        extra["mind"] = float(min_duration_ms)
    return (
        f"SELECT trace_id, min(timestamp) AS start, "
        f"max(toUnixTimestamp64Milli(timestamp) + ifNull(duration_ms, 0)) - min(toUnixTimestamp64Milli(timestamp)) AS duration_ms, "
        f"count() AS spans, countIf(status = 'error') AS failed_spans, "
        f"argMin(operation_name, timestamp) AS root_operation FROM {T} WHERE kind = 'trace_span' AND {_SCOPE} "
        f"GROUP BY trace_id {('HAVING ' + ' AND '.join(having)) if having else ''} ORDER BY start DESC LIMIT {{lim:UInt32}}",
        _params(s, lim=max(1, min(limit, 200)), **extra),
    )


def shape_traces(rows: list[dict]) -> list[dict]:
    return [{
        "trace_id": r["trace_id"], "start": _iso(r["start"]), "duration_ms": _num(r["duration_ms"]), "spans": int(r["spans"]),
        "failed_spans": int(r["failed_spans"]), "root_operation": r["root_operation"],
    } for r in rows]


def trace_detail_query(s: Scope, trace_id: str) -> tuple[str, dict]:
    return (
        f"SELECT timestamp, span_id, parent_span_id, operation_name, service_name, duration_ms, status, attributes "
        f"FROM {T} WHERE kind = 'trace_span' AND trace_id = {{trace:String}} AND {_SCOPE} ORDER BY timestamp LIMIT 2000",
        _params(s, trace=trace_id[:64]),
    )


def trace_logs_query(s: Scope, trace_id: str) -> tuple[str, dict]:
    return logs_query(s, None, None, trace_id, limit=200)


def shape_trace_detail(rows: list[dict]) -> list[dict]:
    return [{
        "span_id": r["span_id"], "parent_span_id": r["parent_span_id"] or None, "operation": r["operation_name"],
        "service": r["service_name"], "start": _iso(r["timestamp"]), "duration_ms": _num(r["duration_ms"]),
        "status": r["status"], "attributes": public_attrs(r.get("attributes")),
    } for r in rows]
